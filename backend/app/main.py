import hashlib
import uuid
from contextlib import contextmanager
from fastapi import FastAPI,UploadFile,File,Depends,HTTPException,Header,Query,Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel,Field
from sqlalchemy import select,text,func,or_
from app.db import SessionLocal
from app.models import MediaAsset,TranslationJob,AppUser,SocialIdentity
from app.storage import client
from app.config import settings
from app.stream_urls import validate_stream_url,capture_seconds_valid,StreamURLRejected
from app.tasks import translate_media
from app.media_preview import issue_playback_token,check_playback_token,parse_byte_range,srt_to_webvtt,InvalidPlaybackToken,InvalidByteRange
from starlette.background import BackgroundTask
from app.auth import router as auth_router, actor_from_request
from starlette.middleware.sessions import SessionMiddleware

app=FastAPI(title="KhmerLive AI — Offline Translation Research MVP",version="0.3.0")
app.add_middleware(SessionMiddleware,secret_key=settings.auth_session_secret,
                   session_cookie="khmerlive_session",same_site="lax",
                   https_only=settings.auth_cookie_secure,max_age=86400*14)
app.include_router(auth_router)

def authorize(request:Request,x_api_key:str|None=Header(default=None)):
    return actor_from_request(request,x_api_key)

def only_owned(query, actor, table):
    if actor["admin"]:
        return query
    return query.where(table.owner_user_id==actor["user_id"])

def owned_job(db, job_id, actor):
    q=only_owned(select(TranslationJob).where(TranslationJob.id==job_id),actor,TranslationJob)
    return db.scalar(q)


@contextmanager
def session():
    with SessionLocal() as db:yield db

@app.get("/api/health/live")
def live():return {"status":"ok","mode":settings.model_mode}

@app.get("/api/health/ready")
def ready():
    with session() as db:db.execute(text("SELECT 1"))
    return {"status":"ready"}

@app.get("/api/models",dependencies=[Depends(authorize)])
def models():
    from app.real_inference import model_paths
    configured=False
    if settings.model_mode=="real_subtitles":
        try:
            model_paths(settings.whisper_model_path,settings.translation_model_path)
            configured=True
        except FileNotFoundError:
            configured=False
    return {"mode":settings.model_mode,"subtitle_translation_configured":configured,
            "speech_dubbing_available":False,
            "note":"Real subtitle mode requires local Whisper/M2M100 weights and an AI worker. Speech dubbing is not implemented."}

@app.post("/api/media",status_code=201,dependencies=[Depends(authorize)])
async def upload(file:UploadFile=File(...),actor:dict=Depends(authorize)):
    name=(file.filename or "upload.mp4").rsplit("/",1)[-1][:255]
    if not name.lower().endswith(".mp4") or file.content_type not in ("video/mp4","application/octet-stream"):
        raise HTTPException(415,"Only MP4 videos supported")
    max_size=settings.max_upload_mb*1024*1024
    # Bounded streaming upload: no full-file reads into application memory.
    import tempfile,os
    with tempfile.TemporaryFile() as tmp:
        digest=hashlib.sha256();size=0
        while chunk:=await file.read(1024*1024):
            size+=len(chunk)
            if size>max_size:raise HTTPException(413,"File too large")
            digest.update(chunk);tmp.write(chunk)
        if size<12:raise HTTPException(400,"Invalid video")
        tmp.seek(0)
        head=tmp.read(12)
        if b"ftyp" not in head:raise HTTPException(415,"Invalid MP4 signature")
        tmp.seek(0)
        mid=str(uuid.uuid4());key=f"uploads/{mid}.mp4"
        client().upload_fileobj(tmp,settings.minio_bucket,key,ExtraArgs={"ContentType":"video/mp4"})
    with session() as db:
        obj=MediaAsset(id=mid,filename=name,object_key=key,content_type="video/mp4",size_bytes=size,sha256=digest.hexdigest(),owner_user_id=actor["user_id"])
        db.add(obj);db.commit()
    return {"media_id":mid,"size_bytes":size,"sha256":digest.hexdigest()}

class JobCreate(BaseModel):
    media_id:str
    source_lang:str=Field(pattern="^(en|km)$")
    target_lang:str=Field(pattern="^(en|km)$")

@app.post("/api/jobs",status_code=202,dependencies=[Depends(authorize)])
def create_job(payload:JobCreate,actor:dict=Depends(authorize)):
    if payload.source_lang==payload.target_lang:raise HTTPException(422,"Language pair must differ")
    if settings.model_mode not in ("demo","real_subtitles"):
        raise HTTPException(503,"Unsupported model mode")
    with session() as db:
        media=db.get(MediaAsset,payload.media_id)
        if media is None or (not actor["admin"] and media.owner_user_id!=actor["user_id"]):
            raise HTTPException(404,"Media not found")
        jid=str(uuid.uuid4())
        job=TranslationJob(id=jid,media_id=payload.media_id,source_lang=payload.source_lang,target_lang=payload.target_lang,status="queued",processing_mode=settings.model_mode,owner_user_id=actor["user_id"])
        db.add(job);db.commit()
    try:translate_media.delay(jid)
    except Exception as exc:
        with session() as db:
            job=db.get(TranslationJob,jid);job.status="dispatch_failed";job.error="Queue dispatch failed";db.commit()
        raise HTTPException(503,"Queue temporarily unavailable") from exc
    return {"job_id":jid,"status":"queued","mode":settings.model_mode}


class StreamJobCreate(BaseModel):
    url:str=Field(min_length=8,max_length=2048)
    source_lang:str=Field(pattern="^(en|km)$")
    target_lang:str=Field(pattern="^(en|km)$")
    capture_seconds:int=Field(default=30,ge=5,le=120)

@app.post("/api/jobs/from-url",status_code=202,dependencies=[Depends(authorize)])
def create_url_job(payload:StreamJobCreate,actor:dict=Depends(authorize)):
    if payload.source_lang==payload.target_lang:
        raise HTTPException(422,"Language pair must differ")
    if settings.model_mode not in ("demo","real_subtitles"):
        raise HTTPException(503,"Unsupported model mode")
    try:
        url=validate_stream_url(payload.url)
        seconds=capture_seconds_valid(payload.capture_seconds)
    except StreamURLRejected as ex:
        raise HTTPException(422,str(ex)) from ex
    mid=str(uuid.uuid4())
    jid=str(uuid.uuid4())
    # Store URL only in PostgreSQL, not in API job responses or logs.
    with session() as db:
        db.add(MediaAsset(id=mid,filename="URL Capture "+mid[:8]+".mp4",
                          object_key="uploads/"+mid+".mp4",
                          content_type="video/mp4",size_bytes=0,
                          sha256="pending",source_url=url,owner_user_id=actor["user_id"],
                          source_kind="url",capture_seconds=seconds))
        db.add(TranslationJob(id=jid,media_id=mid,
                              source_lang=payload.source_lang,target_lang=payload.target_lang,
                              status="queued",progress=0,stage="waiting to capture URL",
                              processing_mode=settings.model_mode,owner_user_id=actor["user_id"]))
        db.commit()
    try:
        translate_media.delay(jid)
    except Exception as exc:
        with session() as db:
            job=db.get(TranslationJob,jid)
            if job:
                job.status="dispatch_failed"
                job.error="Queue dispatch failed"
                db.commit()
        raise HTTPException(503,"Queue dispatch failed") from exc
    return {"job_id":jid,"status":"queued","source_kind":"url",
            "capture_seconds":seconds,"mode":settings.model_mode}

def format_job(job,media):
    return {
        "id":job.id,"media_id":job.media_id,"filename":media.filename,
        "size_bytes":media.size_bytes,"source_kind":media.source_kind,
        "capture_seconds":media.capture_seconds,"status":job.status,
        "progress":job.progress or 0,"stage":job.stage,"cancel_requested":bool(job.cancel_requested),
        "source_lang":job.source_lang,"target_lang":job.target_lang,
        "created_at":job.created_at.isoformat() if job.created_at else None,
        "updated_at":job.updated_at.isoformat() if job.updated_at else None,
        "transcript":job.transcript,"translation":job.translation,
        "processing_mode":job.processing_mode,"has_subtitles":bool(job.subtitle_key),
        "error":job.error,"has_output":bool(job.output_key),"mode":settings.model_mode,
    }

@app.get("/api/dashboard",dependencies=[Depends(authorize)])
def dashboard(actor:dict=Depends(authorize)):
    with session() as db:
        q=only_owned(select(TranslationJob.status,func.count(TranslationJob.id)),actor,TranslationJob)
        rows=db.execute(q.group_by(TranslationJob.status)).all()
        counts=dict(rows)
    return {"total":sum(counts.values()),"queued":counts.get("queued",0),
        "processing":counts.get("processing",0)+counts.get("cancelling",0),"completed":counts.get("completed",0),
        "failed":counts.get("failed",0)+counts.get("dispatch_failed",0),
        "by_status":counts,"mode":settings.model_mode}

@app.get("/api/users",dependencies=[Depends(authorize)])
def list_registered_users(actor:dict=Depends(authorize),
                          limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0)):
    # Admin-only directory; ordinary social users can view only their own profile.
    if not actor["admin"]:
        raise HTTPException(403,"Admin access required for user directory")
    with session() as db:
        total=db.scalar(select(func.count(AppUser.id))) or 0
        users=db.scalars(select(AppUser).order_by(AppUser.created_at.desc())
                         .limit(limit).offset(offset)).all()
        user_ids=[u.id for u in users]
        identities=db.scalars(select(SocialIdentity).where(
            SocialIdentity.user_id.in_(user_ids))).all() if user_ids else []
        provider_map={}
        for identity in identities:
            provider_map.setdefault(identity.user_id,[]).append(identity.provider)
        return {"total":total,"limit":limit,"offset":offset,
                "items":[{"id":u.id,"display_name":u.display_name,"email":u.email,
                          "created_at":u.created_at.isoformat() if u.created_at else None,
                          "providers":provider_map.get(u.id,[])} for u in users]}

@app.get("/api/system",dependencies=[Depends(authorize)])
def system_status():
    checks={"api":"online","database":"unknown","redis":"unknown","storage":"unknown","worker":"unknown"}
    try:
        with session() as db:db.execute(text("SELECT 1"))
        checks["database"]="online"
    except Exception:checks["database"]="offline"
    try:
        from redis import Redis
        checks["redis"]="online" if Redis.from_url(settings.redis_url,socket_timeout=1,socket_connect_timeout=1).ping() else "offline"
    except Exception:checks["redis"]="offline"
    try:
        client().head_bucket(Bucket=settings.minio_bucket)
        checks["storage"]="online"
    except Exception:checks["storage"]="offline"
    try:
        from app.tasks import celery_app
        checks["worker"]="online" if celery_app.control.inspect(timeout=0.8).ping() else "unknown"
    except Exception:checks["worker"]="unknown"
    return {"services":checks,"mode":settings.model_mode}

@app.get("/api/jobs",dependencies=[Depends(authorize)])
def list_jobs(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),
              status:str|None=Query(None),search:str|None=Query(None,max_length=200),
              actor:dict=Depends(authorize)):
    with session() as db:
        q=only_owned(select(TranslationJob,MediaAsset).join(MediaAsset,TranslationJob.media_id==MediaAsset.id),actor,TranslationJob)
        if status and status!="all":
            if status=="active":q=q.where(TranslationJob.status.in_(["queued","processing","cancelling"]))
            elif status=="failed":q=q.where(TranslationJob.status.in_(["failed","dispatch_failed"]))
            elif status in ("queued","processing","completed","dispatch_failed"):
                q=q.where(TranslationJob.status==status)
            else:raise HTTPException(422,"Unsupported job status")
        if search:
            term=f"%{search.strip()}%"
            q=q.where(or_(MediaAsset.filename.ilike(term),TranslationJob.id.ilike(term)))
        total=db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        rows=db.execute(q.order_by(TranslationJob.created_at.desc(),TranslationJob.id.desc()).offset(offset).limit(limit)).all()
        return {"items":[format_job(j,m) for j,m in rows],"total":total,"limit":limit,"offset":offset}

@app.get("/api/jobs/{job_id}",dependencies=[Depends(authorize)])
def get_job(job_id:str,actor:dict=Depends(authorize)):
    with session() as db:
        q=only_owned(select(TranslationJob,MediaAsset).join(MediaAsset,TranslationJob.media_id==MediaAsset.id).where(TranslationJob.id==job_id),actor,TranslationJob)
        row=db.execute(q).first()
        if row is None:raise HTTPException(404,"Not found")
        return format_job(*row)


@app.post("/api/jobs/{job_id}/cancel",dependencies=[Depends(authorize)])
def cancel_job(job_id:str,actor:dict=Depends(authorize)):
    with session() as db:
        j=db.scalar(only_owned(select(TranslationJob).where(TranslationJob.id==job_id).with_for_update(),actor,TranslationJob))
        if j is None:raise HTTPException(404,"Job not found")
        if j.status not in ("queued","processing","cancelling"):
            raise HTTPException(409,"Job is not cancellable")
        j.cancel_requested=True
        if j.status=="queued":
            j.status="cancelled"
            j.stage="cancelled before execution"
        else:
            j.status="cancelling"
            j.stage="cancellation requested"
        db.commit()
        return {"id":j.id,"status":j.status}

@app.post("/api/jobs/{job_id}/retry",dependencies=[Depends(authorize)])
def retry_job(job_id:str,actor:dict=Depends(authorize)):
    with session() as db:
        j=db.scalar(only_owned(select(TranslationJob).where(TranslationJob.id==job_id).with_for_update(),actor,TranslationJob))
        if j is None:raise HTTPException(404,"Job not found")
        if j.status not in ("failed","dispatch_failed","cancelled"):
            raise HTTPException(409,"Only failed or cancelled jobs can be retried")
        j.status="queued"
        j.cancel_requested=False
        j.progress=0
        j.stage="queued for retry"
        j.error=None
        j.output_key=None
        j.subtitle_key=None
        j.transcript=None
        j.translation=None
        db.commit()
    try:translate_media.delay(job_id)
    except Exception as exc:
        with session() as db:
            j=db.get(TranslationJob,job_id)
            if j and j.status=="queued":
                j.status="dispatch_failed"
                j.error="Queue dispatch failed"
                db.commit()
        raise HTTPException(503,"Queue dispatch failed") from exc
    return {"id":job_id,"status":"queued"}

@app.get("/api/jobs/{job_id}/player-token")
def player_token(job_id:str,actor:dict=Depends(authorize)):
    """Mint an expiring, job-scoped playback grant for HTML5 video/track tags.

    HTML video tags cannot attach X-API-Key. This grant avoids exposing the
    global API key in a URL and is constrained to one authorized job.
    """
    with session() as db:
        job=owned_job(db,job_id,actor)
        if job is None or job.status!="completed" or not job.output_key:
            raise HTTPException(404,"Playable video not available")
        grant=issue_playback_token(job.id,job.owner_user_id,settings.auth_session_secret,180)
        return {"token":grant,"expires_in":180,
                "video_url":f"/api/jobs/{job.id}/preview?token={grant}",
                "captions_url":f"/api/jobs/{job.id}/captions.vtt?token={grant}" if job.subtitle_key else None}

def playback_job(job_id:str,token:str):
    with session() as db:
        job=db.get(TranslationJob,job_id)
        if job is None or job.status!="completed" or not job.output_key:
            raise HTTPException(404,"Video not available")
        try:
            check_playback_token(token,job_id,job.owner_user_id,settings.auth_session_secret)
        except InvalidPlaybackToken as exc:
            raise HTTPException(403,"Playback grant expired or invalid") from exc
        return job.output_key,job.subtitle_key

@app.get("/api/jobs/{job_id}/preview")
def preview_video(job_id:str,request:Request,token:str=Query(min_length=20,max_length=2048)):
    key,_=playback_job(job_id,token)
    s3=client()
    try:
        head=s3.head_object(Bucket=settings.minio_bucket,Key=key)
        size=int(head["ContentLength"])
    except Exception as exc:
        raise HTTPException(502,"Media is currently unavailable") from exc
    try:
        byte_range=parse_byte_range(request.headers.get("range"),size)
    except InvalidByteRange as exc:
        raise HTTPException(416,"Invalid byte range",
                            headers={"Content-Range":f"bytes */{size}"}) from exc
    request_args={"Bucket":settings.minio_bucket,"Key":key}
    if byte_range is not None:
        request_args["Range"]=byte_range.s3_range
    try:
        response=s3.get_object(**request_args)
    except Exception as exc:
        raise HTTPException(502,"Media playback unavailable") from exc
    body=response["Body"]
    headers={"Accept-Ranges":"bytes","Content-Length":str(byte_range.length if byte_range else size),
             "Content-Disposition":"inline","Cache-Control":"private, no-store",
             "Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff"}
    if byte_range:
        headers["Content-Range"]=byte_range.content_range
    return StreamingResponse(body.iter_chunks(chunk_size=1024*256),
        status_code=206 if byte_range else 200,media_type="video/mp4",
        headers=headers,background=BackgroundTask(body.close))

@app.get("/api/jobs/{job_id}/captions.vtt")
def preview_captions(job_id:str,token:str=Query(min_length=20,max_length=2048)):
    _,key=playback_job(job_id,token)
    if not key:
        raise HTTPException(404,"Translated captions not available")
    try:
        obj=client().get_object(Bucket=settings.minio_bucket,Key=key)
        body=obj["Body"]
        try:
            raw=body.read(2_000_001)
        finally:
            body.close()
    except Exception as exc:
        raise HTTPException(502,"Caption storage unavailable") from exc
    if len(raw)>2_000_000:
        raise HTTPException(413,"Captions too large")
    try:
        captions=srt_to_webvtt(raw.decode("utf-8"))
    except (UnicodeError,ValueError) as exc:
        raise HTTPException(422,"Invalid subtitle format") from exc
    return PlainTextResponse(captions,media_type="text/vtt; charset=utf-8",
        headers={"Cache-Control":"private, no-store","Referrer-Policy":"no-referrer"})

@app.get("/api/jobs/{job_id}/subtitles",dependencies=[Depends(authorize)])
def download_subtitles(job_id:str,actor:dict=Depends(authorize)):
    with session() as db:
        j=owned_job(db,job_id,actor)
        if j is None or not j.subtitle_key:
            raise HTTPException(404,"Translated subtitles not available")
        key=j.subtitle_key
    try:
        obj=client().get_object(Bucket=settings.minio_bucket,Key=key)
    except Exception as exc:
        raise HTTPException(502,"Subtitle storage unavailable") from exc
    return StreamingResponse(obj["Body"].iter_chunks(chunk_size=65536),
        media_type="application/x-subrip; charset=utf-8",
        headers={"Content-Disposition":f'attachment; filename="{job_id}.srt"'})

@app.get("/api/jobs/{job_id}/download",dependencies=[Depends(authorize)])
def download(job_id:str,actor:dict=Depends(authorize)):
    with session() as db:
        j=owned_job(db,job_id,actor)
        if not j or not j.output_key:raise HTTPException(404,"Output not found")
        key=j.output_key
    try:response=client().get_object(Bucket=settings.minio_bucket,Key=key)
    except Exception as exc:raise HTTPException(502,"Storage unavailable") from exc
    return StreamingResponse(response["Body"].iter_chunks(chunk_size=1024*1024),media_type="video/mp4",headers={"Content-Disposition":f'attachment; filename="{job_id}.mp4"'})
