import hashlib
import logging
from datetime import datetime,timezone
import uuid
from contextlib import contextmanager
from fastapi import FastAPI,UploadFile,File,Depends,HTTPException,Header,Query,Request,Path
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel,Field
from sqlalchemy import select,text,func,or_,delete
from app.db import SessionLocal
from app.models import MediaAsset,TranslationJob,AppUser,SocialIdentity,JobEvent
from app.joblog import log_event
from app.storage import client
from app.config import settings
from app.stream_urls import validate_stream_url,capture_seconds_valid,StreamURLRejected
from app.youtube import is_youtube_host,youtube_video_id,canonical_url,fetch_info,YouTubeURLRejected
from app.tasks import translate_media
from app.llm_postedit import llm_status
from app.media_preview import issue_playback_token,check_playback_token,parse_byte_range,srt_to_webvtt,InvalidPlaybackToken,InvalidByteRange
from starlette.background import BackgroundTask
from app.auth import router as auth_router, actor_from_request
from starlette.middleware.sessions import SessionMiddleware

logger=logging.getLogger(__name__)

ACTIVE_STATUSES=("queued","processing","cancelling")
JOB_SORTS={
    "newest":lambda:(TranslationJob.created_at.desc(),TranslationJob.id.desc()),
    "oldest":lambda:(TranslationJob.created_at.asc(),TranslationJob.id.asc()),
    "name_asc":lambda:(func.lower(MediaAsset.filename).asc(),TranslationJob.created_at.desc()),
    "name_desc":lambda:(func.lower(MediaAsset.filename).desc(),TranslationJob.created_at.desc()),
    "status":lambda:(TranslationJob.status.asc(),TranslationJob.created_at.desc()),
    "updated":lambda:(TranslationJob.updated_at.desc(),TranslationJob.id.desc()),
}
MEDIA_SORTS={
    "newest":lambda:(MediaAsset.created_at.desc(),MediaAsset.id.desc()),
    "oldest":lambda:(MediaAsset.created_at.asc(),MediaAsset.id.asc()),
    "name_asc":lambda:(func.lower(MediaAsset.filename).asc(),MediaAsset.id.asc()),
    "name_desc":lambda:(func.lower(MediaAsset.filename).desc(),MediaAsset.id.asc()),
    "size_desc":lambda:(MediaAsset.size_bytes.desc(),MediaAsset.id.asc()),
    "size_asc":lambda:(MediaAsset.size_bytes.asc(),MediaAsset.id.asc()),
}

def search_term(search:str|None)->str|None:
    """ILIKE pattern with %, _ and \\ escaped so user input matches literally."""
    if not search or not search.strip():return None
    esc=search.strip().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
    return f"%{esc}%"

def delete_storage(keys)->bool:
    """Best-effort removal of S3 objects after their DB rows are gone. Returns False on failure."""
    keys=sorted({k for k in keys if k})
    if not keys:return True
    try:
        client().delete_objects(Bucket=settings.minio_bucket,Delete={"Objects":[{"Key":k} for k in keys],"Quiet":True})
        return True
    except Exception as exc:
        logger.warning("Could not delete %d storage object(s): %s",len(keys),exc)
        return False

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

def visible(query, actor, table):
    """only_owned plus hiding rows that are in the Trash."""
    return only_owned(query,actor,table).where(table.deleted_at.is_(None))

def owned_job(db, job_id, actor):
    q=visible(select(TranslationJob).where(TranslationJob.id==job_id),actor,TranslationJob)
    return db.scalar(q)

def require_admin(actor):
    if not actor["admin"]:
        raise HTTPException(403,"Admin access required for the Trash")


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
    from app.khmer_tts import require_tts_model
    dubbing_ready=False
    if settings.model_mode=="real_subtitles" and settings.enable_khmer_dubbing:
        try:
            require_tts_model(settings.khmer_tts_model_path)
            dubbing_ready=True
        except FileNotFoundError:
            pass
    import json,os
    installed={}
    try:
        with open(os.path.join(os.path.dirname(settings.whisper_model_path.rstrip("/")),"manifest.lock.json")) as fh:
            for m in json.load(fh).get("models",[]):
                installed[m.get("component")]={"id":m.get("id"),"license":m.get("card_license"),
                                               "revision":(m.get("revision") or "")[:12]}
    except (OSError,ValueError):
        pass
    return {"mode":settings.model_mode,"subtitle_translation_configured":configured,
            "installed":installed,"max_video_duration_seconds":settings.max_video_duration_seconds,
            "youtube_enabled":settings.youtube_enabled,
            "speech_dubbing_available":dubbing_ready,
            "khmer_dubbing_enabled":settings.enable_khmer_dubbing,
            "llm":llm_status(),
            "note":"English to Khmer jobs replace source audio with offline Khmer TTS when enabled. Khmer to English remains subtitle-only."}

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

def ensure_translation_ready(target_lang:str):
    if settings.model_mode=="real_subtitles":
        from app.real_inference import model_paths
        try:
            model_paths(settings.whisper_model_path,settings.translation_model_path)
            if settings.enable_khmer_dubbing and target_lang=="km":
                from app.khmer_tts import require_tts_model
                require_tts_model(settings.khmer_tts_model_path)
        except FileNotFoundError as exc:
            raise HTTPException(503,
                "Offline ASR, translation or Khmer TTS model weights are not installed. "
                "Download and validate all required offline models first.") from exc
    elif settings.model_mode!="demo":
        raise HTTPException(503,"Unsupported MODEL_MODE")

class JobCreate(BaseModel):
    media_id:str
    source_lang:str=Field(pattern="^(en|km)$")
    target_lang:str=Field(pattern="^(en|km)$")

@app.post("/api/jobs",status_code=202,dependencies=[Depends(authorize)])
def create_job(payload:JobCreate,actor:dict=Depends(authorize)):
    if payload.source_lang==payload.target_lang:raise HTTPException(422,"Language pair must differ")
    ensure_translation_ready(payload.target_lang)
    with session() as db:
        media=db.get(MediaAsset,payload.media_id)
        if media is None or media.deleted_at is not None or (not actor["admin"] and media.owner_user_id!=actor["user_id"]):
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


@app.get("/api/youtube/info",dependencies=[Depends(authorize)])
def youtube_info(url:str=Query(min_length=8,max_length=2048),actor:dict=Depends(authorize)):
    """Title/length preview for a YouTube link before a job is created."""
    if not actor["admin"] and not settings.stream_url_allow_users:
        raise HTTPException(403,"URL ingestion is restricted to trusted administrators")
    if not settings.youtube_enabled:
        raise HTTPException(403,"YouTube ingestion is disabled on this server")
    try:
        video_id=youtube_video_id(url)
    except YouTubeURLRejected as ex:
        raise HTTPException(422,str(ex)) from ex
    try:
        info=fetch_info(video_id)
    except Exception as ex:
        raise HTTPException(502,"Could not read this YouTube video: "+str(ex)[:200]) from ex
    info["trimmed_to_seconds"]=settings.max_video_duration_seconds if (info.get("duration") or 0)>settings.max_video_duration_seconds else None
    return info

class StreamJobCreate(BaseModel):
    url:str=Field(min_length=8,max_length=2048)
    source_lang:str=Field(pattern="^(en|km)$")
    target_lang:str=Field(pattern="^(en|km)$")
    capture_seconds:int=Field(default=30,ge=5,le=120)

@app.post("/api/jobs/from-url",status_code=202,dependencies=[Depends(authorize)])
def create_url_job(payload:StreamJobCreate,actor:dict=Depends(authorize)):
    if not actor["admin"] and not settings.stream_url_allow_users:
        raise HTTPException(403,"URL stream ingestion is restricted to trusted administrators")
    if payload.source_lang==payload.target_lang:
        raise HTTPException(422,"Language pair must differ")
    ensure_translation_ready(payload.target_lang)
    youtube_id=None
    try:
        if is_youtube_host(payload.url):
            if not settings.youtube_enabled:
                raise HTTPException(403,"YouTube ingestion is disabled on this server (YOUTUBE_ENABLED=false)")
            youtube_id=youtube_video_id(payload.url)
            # Only the canonical single-video URL is stored and handed to yt-dlp.
            url=canonical_url(youtube_id)
            seconds=None
        else:
            url=validate_stream_url(payload.url)
            seconds=capture_seconds_valid(payload.capture_seconds)
    except (StreamURLRejected,YouTubeURLRejected) as ex:
        raise HTTPException(422,str(ex)) from ex
    mid=str(uuid.uuid4())
    jid=str(uuid.uuid4())
    kind="youtube" if youtube_id else "url"
    # Store URL only in PostgreSQL, not in API job responses or logs.
    with session() as db:
        db.add(MediaAsset(id=mid,filename=("YouTube "+youtube_id if youtube_id else "URL Capture "+mid[:8])+".mp4",
                          object_key="uploads/"+mid+".mp4",
                          content_type="video/mp4",size_bytes=0,
                          sha256="pending",source_url=url,owner_user_id=actor["user_id"],
                          source_kind=kind,capture_seconds=seconds))
        db.add(TranslationJob(id=jid,media_id=mid,
                              source_lang=payload.source_lang,target_lang=payload.target_lang,
                              status="queued",progress=0,stage="waiting to download YouTube video" if youtube_id else "waiting to capture URL",
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
    return {"job_id":jid,"status":"queued","source_kind":kind,
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
        "has_khmer_voice":bool(job.output_key and job.output_key.endswith(".khmer-dubbed.mp4")),
        "error":job.error,"has_output":bool(job.output_key),"mode":settings.model_mode,
        "timings":_timings(job.timings),
    }

def _timings(raw):
    import json
    try:return json.loads(raw) if raw else None
    except ValueError:return None

@app.get("/api/dashboard",dependencies=[Depends(authorize)])
def dashboard(actor:dict=Depends(authorize)):
    with session() as db:
        q=visible(select(TranslationJob.status,func.count(TranslationJob.id)),actor,TranslationJob)
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

def host_metrics():
    """Best-effort container resource usage for the System Health cards."""
    import os,shutil
    out={"cpu_percent":None,"memory_used_bytes":None,"memory_total_bytes":None,
         "disk_used_bytes":None,"disk_total_bytes":None}
    try:out["cpu_percent"]=round(min(100.0,os.getloadavg()[0]*100/(os.cpu_count() or 1)),1)
    except OSError:pass
    try:
        info={}
        with open("/proc/meminfo") as fh:
            for line in fh:
                k,v=line.split(":",1);info[k]=int(v.split()[0])*1024
        out["memory_total_bytes"]=info["MemTotal"]
        out["memory_used_bytes"]=info["MemTotal"]-info.get("MemAvailable",info.get("MemFree",0))
    except (OSError,KeyError,ValueError):pass
    try:
        du=shutil.disk_usage("/")
        out["disk_used_bytes"]=du.used;out["disk_total_bytes"]=du.total
    except OSError:pass
    return out

@app.get("/api/system",dependencies=[Depends(authorize)])
def system_status():
    import time
    checks={"api":"online","database":"unknown","redis":"unknown","storage":"unknown","worker":"unknown"}
    latency={"api":0}
    t=time.perf_counter()
    try:
        with session() as db:db.execute(text("SELECT 1"))
        checks["database"]="online"
    except Exception:checks["database"]="offline"
    latency["database"]=round((time.perf_counter()-t)*1000);t=time.perf_counter()
    try:
        from redis import Redis
        checks["redis"]="online" if Redis.from_url(settings.redis_url,socket_timeout=1,socket_connect_timeout=1).ping() else "offline"
    except Exception:checks["redis"]="offline"
    latency["redis"]=round((time.perf_counter()-t)*1000);t=time.perf_counter()
    try:
        client().head_bucket(Bucket=settings.minio_bucket)
        checks["storage"]="online"
    except Exception:checks["storage"]="offline"
    latency["storage"]=round((time.perf_counter()-t)*1000);t=time.perf_counter()
    try:
        from app.tasks import celery_app
        checks["worker"]="online" if celery_app.control.inspect(timeout=0.8).ping() else "unknown"
    except Exception:checks["worker"]="unknown"
    # Celery's ping waits for its full timeout, so no meaningful latency for the worker.
    return {"services":checks,"latency_ms":latency,"mode":settings.model_mode,"host":host_metrics()}

@app.get("/api/jobs",dependencies=[Depends(authorize)])
def list_jobs(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),
              status:str|None=Query(None),search:str|None=Query(None,max_length=200),
              source:str|None=Query(None,pattern="^(all|upload|url|youtube)$"),
              sort:str=Query("newest",pattern="^("+"|".join(JOB_SORTS)+")$"),
              media_id:str|None=Query(None,max_length=36),
              actor:dict=Depends(authorize)):
    with session() as db:
        q=visible(select(TranslationJob,MediaAsset).join(MediaAsset,TranslationJob.media_id==MediaAsset.id),actor,TranslationJob)
        if status and status!="all":
            if status=="active":q=q.where(TranslationJob.status.in_(["queued","processing","cancelling"]))
            elif status=="failed":q=q.where(TranslationJob.status.in_(["failed","dispatch_failed"]))
            elif status in ("queued","processing","completed","dispatch_failed"):
                q=q.where(TranslationJob.status==status)
            else:raise HTTPException(422,"Unsupported job status")
        if source and source!="all":
            q=q.where(MediaAsset.source_kind==source)
        if media_id:
            q=q.where(TranslationJob.media_id==media_id)
        if term:=search_term(search):
            q=q.where(or_(MediaAsset.filename.ilike(term,escape="\\"),TranslationJob.id.ilike(term,escape="\\"),
                          MediaAsset.source_url.ilike(term,escape="\\")))
        total=db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        rows=db.execute(q.order_by(*JOB_SORTS[sort]()).offset(offset).limit(limit)).all()
        return {"items":[format_job(j,m) for j,m in rows],"total":total,"limit":limit,"offset":offset}

@app.get("/api/jobs/{job_id}",dependencies=[Depends(authorize)])
def get_job(job_id:str,actor:dict=Depends(authorize)):
    with session() as db:
        q=visible(select(TranslationJob,MediaAsset).join(MediaAsset,TranslationJob.media_id==MediaAsset.id).where(TranslationJob.id==job_id),actor,TranslationJob)
        row=db.execute(q).first()
        if row is None:raise HTTPException(404,"Not found")
        return format_job(*row)


def actor_label(actor)->str:
    return actor["user_id"] or "admin"

@app.get("/api/jobs/{job_id}/events",dependencies=[Depends(authorize)])
def job_events(job_id:str,stage:str|None=Query(None,max_length=40),actor:dict=Depends(authorize)):
    """Pipeline log for a job. stage=llm returns only the LLM post-edit line records."""
    import json
    with session() as db:
        if owned_job(db,job_id,actor) is None:raise HTTPException(404,"Job not found")
        q=select(JobEvent).where(JobEvent.job_id==job_id)
        if stage:q=q.where(JobEvent.stage==stage)
        rows=db.scalars(q.order_by(JobEvent.id.asc()).limit(5000)).all()
        def data(raw):
            try:return json.loads(raw) if raw else None
            except ValueError:return None
        return {"items":[{"id":e.id,"at":e.created_at.isoformat() if e.created_at else None,"stage":e.stage,
                          "level":e.level,"message":e.message,"seconds":e.seconds,"data":data(e.data)} for e in rows]}

@app.delete("/api/jobs/{job_id}",dependencies=[Depends(authorize)])
def delete_job(job_id:str,actor:dict=Depends(authorize)):
    """Move a finished, failed or cancelled job to the Trash. Files are kept until an admin purges it."""
    with session() as db:
        j=db.scalar(visible(select(TranslationJob).where(TranslationJob.id==job_id).with_for_update(),actor,TranslationJob))
        if j is None:raise HTTPException(404,"Job not found")
        if j.status in ACTIVE_STATUSES:
            raise HTTPException(409,"Cancel the job before deleting it")
        j.deleted_at=datetime.now(timezone.utc);j.deleted_by=actor_label(actor)
        db.commit()
    log_event(job_id,"job","Moved to Trash",level="warning",by=actor_label(actor))
    return {"id":job_id,"trashed":True}

@app.get("/api/media",dependencies=[Depends(authorize)])
def list_media(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),
               search:str|None=Query(None,max_length=200),
               source:str|None=Query(None,pattern="^(all|upload|url|youtube)$"),
               sort:str=Query("newest",pattern="^("+"|".join(MEDIA_SORTS)+")$"),
               actor:dict=Depends(authorize)):
    """Source videos (uploads and links) with how many translation jobs use each one."""
    with session() as db:
        q=visible(select(MediaAsset),actor,MediaAsset)
        if source and source!="all":q=q.where(MediaAsset.source_kind==source)
        if term:=search_term(search):
            q=q.where(or_(MediaAsset.filename.ilike(term,escape="\\"),MediaAsset.id.ilike(term,escape="\\"),
                          MediaAsset.source_url.ilike(term,escape="\\")))
        total=db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        media=db.scalars(q.order_by(*MEDIA_SORTS[sort]()).offset(offset).limit(limit)).all()
        stats={}
        if media:
            rows=db.execute(select(TranslationJob.media_id,TranslationJob.status,func.count())
                            .where(TranslationJob.media_id.in_([m.id for m in media]),TranslationJob.deleted_at.is_(None))
                            .group_by(TranslationJob.media_id,TranslationJob.status)).all()
            for mid,status,n in rows:
                st=stats.setdefault(mid,{"jobs":0,"active":0,"completed":0})
                st["jobs"]+=n
                if status in ACTIVE_STATUSES:st["active"]+=n
                if status=="completed":st["completed"]+=n
        items=[{"id":m.id,"filename":m.filename,"size_bytes":m.size_bytes,"source_kind":m.source_kind,
                "source_url":m.source_url,"capture_seconds":m.capture_seconds,
                "created_at":m.created_at.isoformat() if m.created_at else None,
                **stats.get(m.id,{"jobs":0,"active":0,"completed":0})} for m in media]
        return {"items":items,"total":total,"limit":limit,"offset":offset}

@app.delete("/api/media/{media_id}",dependencies=[Depends(authorize)])
def delete_media(media_id:str,actor:dict=Depends(authorize)):
    """Move a source video and all of its jobs to the Trash (restorable by an admin)."""
    with session() as db:
        m=db.scalar(visible(select(MediaAsset).where(MediaAsset.id==media_id).with_for_update(),actor,MediaAsset))
        if m is None:raise HTTPException(404,"Video not found")
        jobs=db.scalars(select(TranslationJob).where(TranslationJob.media_id==media_id,
                                                      TranslationJob.deleted_at.is_(None)).with_for_update()).all()
        if any(j.status in ACTIVE_STATUSES for j in jobs):
            raise HTTPException(409,"This video has jobs in progress. Cancel them before deleting the video")
        now=datetime.now(timezone.utc);who=actor_label(actor)
        m.deleted_at=now;m.deleted_by=who
        for j in jobs:j.deleted_at=now;j.deleted_by=who   # same timestamp: restored together
        db.commit()
    return {"id":media_id,"trashed":True,"jobs_trashed":len(jobs)}

# ---------------- Trash (admin only) ----------------

TRASH_SORTS={"deleted_newest":lambda c:c.deleted_at.desc(),"deleted_oldest":lambda c:c.deleted_at.asc(),
             "name_asc":lambda c:func.lower(c.filename).asc(),"name_desc":lambda c:func.lower(c.filename).desc()}

@app.get("/api/trash",dependencies=[Depends(authorize)])
def list_trash(kind:str=Query("all",pattern="^(all|job|video)$"),search:str|None=Query(None,max_length=200),
               sort:str=Query("deleted_newest",pattern="^("+"|".join(TRASH_SORTS)+")$"),
               limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),actor:dict=Depends(authorize)):
    require_admin(actor)
    term=search_term(search)
    with session() as db:
        items=[]
        if kind in ("all","video"):
            q=select(MediaAsset).where(MediaAsset.deleted_at.is_not(None))
            if term:q=q.where(or_(MediaAsset.filename.ilike(term,escape="\\"),MediaAsset.id.ilike(term,escape="\\")))
            for m in db.scalars(q):
                n=db.scalar(select(func.count()).where(TranslationJob.media_id==m.id)) or 0
                items.append({"kind":"video","id":m.id,"filename":m.filename,"source_kind":m.source_kind,
                              "size_bytes":m.size_bytes,"status":None,"jobs":n,"media_id":m.id,
                              "owner_user_id":m.owner_user_id,"deleted_by":m.deleted_by,"deleted_at":m.deleted_at})
        if kind in ("all","job"):
            # Jobs trashed along with their video are listed under that video, not separately.
            q=(select(TranslationJob,MediaAsset).join(MediaAsset,TranslationJob.media_id==MediaAsset.id)
               .where(TranslationJob.deleted_at.is_not(None),MediaAsset.deleted_at.is_(None)))
            if term:q=q.where(or_(MediaAsset.filename.ilike(term,escape="\\"),TranslationJob.id.ilike(term,escape="\\")))
            for j,m in db.execute(q):
                items.append({"kind":"job","id":j.id,"filename":m.filename,"source_kind":m.source_kind,
                              "size_bytes":m.size_bytes,"status":j.status,"jobs":None,"media_id":m.id,
                              "owner_user_id":j.owner_user_id,"deleted_by":j.deleted_by,"deleted_at":j.deleted_at})
        names=dict(db.execute(select(AppUser.id,AppUser.display_name)).all())
    key={"deleted_newest":(lambda i:i["deleted_at"],True),"deleted_oldest":(lambda i:i["deleted_at"],False),
         "name_asc":(lambda i:i["filename"].lower(),False),"name_desc":(lambda i:i["filename"].lower(),True)}[sort]
    items.sort(key=key[0],reverse=key[1])
    for i in items:
        i["deleted_at"]=i["deleted_at"].isoformat() if i["deleted_at"] else None
        i["owner_name"]=names.get(i["owner_user_id"])
        i["deleted_by_name"]="Administrator" if i["deleted_by"]=="admin" else names.get(i["deleted_by"],i["deleted_by"])
    return {"items":items[offset:offset+limit],"total":len(items),"limit":limit,"offset":offset}

def _trashed(db,kind,item_id):
    model=MediaAsset if kind=="video" else TranslationJob
    row=db.scalar(select(model).where(model.id==item_id,model.deleted_at.is_not(None)).with_for_update())
    if row is None:raise HTTPException(404,"Not in the Trash")
    return row

@app.post("/api/trash/{kind}/{item_id}/restore",dependencies=[Depends(authorize)])
def restore_trash(kind:str=Path(pattern="^(job|video)$"),item_id:str=Path(max_length=36),actor:dict=Depends(authorize)):
    require_admin(actor)
    with session() as db:
        row=_trashed(db,kind,item_id)
        restored=0
        if kind=="video":
            # Bring back the jobs that were trashed together with the video.
            for j in db.scalars(select(TranslationJob).where(TranslationJob.media_id==row.id,
                                                              TranslationJob.deleted_at==row.deleted_at)):
                j.deleted_at=None;j.deleted_by=None;restored+=1
        else:
            m=db.get(MediaAsset,row.media_id)
            if m is not None and m.deleted_at is not None:
                m.deleted_at=None;m.deleted_by=None   # a job needs its source video
        row.deleted_at=None;row.deleted_by=None
        db.commit()
    if kind=="job":log_event(item_id,"job","Restored from Trash")
    return {"kind":kind,"id":item_id,"restored":True,"jobs_restored":restored}

def _purge(db,kind,row)->list:
    """Hard-delete a trashed row (a video takes all of its jobs). Returns storage keys to remove."""
    if kind=="job":
        db.execute(delete(JobEvent).where(JobEvent.job_id==row.id))
        keys=[row.output_key,row.subtitle_key];db.delete(row);return keys
    jobs=db.scalars(select(TranslationJob).where(TranslationJob.media_id==row.id)).all()
    if any(j.deleted_at is None for j in jobs):
        raise HTTPException(409,"Restore or trash this video's remaining jobs first")
    keys=[row.object_key]+[k for j in jobs for k in (j.output_key,j.subtitle_key)]
    db.execute(delete(JobEvent).where(JobEvent.job_id.in_([j.id for j in jobs])))
    db.execute(delete(TranslationJob).where(TranslationJob.media_id==row.id))
    db.delete(row);return keys

@app.delete("/api/trash/{kind}/{item_id}",dependencies=[Depends(authorize)])
def purge_trash_item(kind:str=Path(pattern="^(job|video)$"),item_id:str=Path(max_length=36),actor:dict=Depends(authorize)):
    """Permanently delete one Trash item and its stored files. Cannot be undone."""
    require_admin(actor)
    with session() as db:
        keys=_purge(db,kind,_trashed(db,kind,item_id));db.commit()
    return {"kind":kind,"id":item_id,"deleted":True,"storage_cleaned":delete_storage(keys)}

@app.delete("/api/trash",dependencies=[Depends(authorize)])
def empty_trash(actor:dict=Depends(authorize)):
    """Empty the Trash: permanently delete every trashed job and video and their files."""
    require_admin(actor)
    keys=[];jobs=0;videos=0
    with session() as db:
        for j in db.scalars(select(TranslationJob).join(MediaAsset,TranslationJob.media_id==MediaAsset.id)
                            .where(TranslationJob.deleted_at.is_not(None),MediaAsset.deleted_at.is_(None)).with_for_update()):
            keys+=_purge(db,"job",j);jobs+=1
        for m in db.scalars(select(MediaAsset).where(MediaAsset.deleted_at.is_not(None)).with_for_update()):
            jobs+=db.scalar(select(func.count()).where(TranslationJob.media_id==m.id)) or 0
            keys+=_purge(db,"video",m);videos+=1
        db.commit()
    return {"deleted":True,"jobs_deleted":jobs,"videos_deleted":videos,"storage_cleaned":delete_storage(keys)}

@app.post("/api/jobs/{job_id}/cancel",dependencies=[Depends(authorize)])
def cancel_job(job_id:str,actor:dict=Depends(authorize)):
    with session() as db:
        j=db.scalar(visible(select(TranslationJob).where(TranslationJob.id==job_id).with_for_update(),actor,TranslationJob))
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
        status=j.status
    log_event(job_id,"job","Cancel requested",level="warning",by=actor_label(actor))
    if status=="cancelling":
        status=abort_running_job(job_id) or status
    return {"id":job_id,"status":status}

def abort_running_job(job_id:str)->str|None:
    """Terminate the worker process running this job right away (SIGTERM → job unwinds and cleans up).

    If no live worker is running it (orphaned by a restart), mark it cancelled now.
    Returns the new status when it is already final, else None (worker finishes the abort).
    """
    from app.tasks import celery_app
    try:
        active=celery_app.control.inspect(timeout=1.0).active()
    except Exception as exc:
        logger.warning("Could not reach workers to abort job %s: %s",job_id,exc)
        return None
    # The worker's main process answers even while a job runs, so no reply means no live worker.
    for tasks in (active or {}).values():
        for t in tasks:
            if (t.get("args") or [None])[0]==job_id:
                celery_app.control.revoke(t["id"],terminate=True,signal="SIGTERM")
                return None
    with session() as db:
        j=db.scalar(select(TranslationJob).where(TranslationJob.id==job_id).with_for_update())
        if j is not None and j.status=="cancelling":
            j.status="cancelled";j.stage="cancelled";db.commit()
            return "cancelled"
    return None

@app.post("/api/jobs/{job_id}/retry",dependencies=[Depends(authorize)])
def retry_job(job_id:str,actor:dict=Depends(authorize)):
    with session() as db:
        j=db.scalar(visible(select(TranslationJob).where(TranslationJob.id==job_id).with_for_update(),actor,TranslationJob))
        if j is None:raise HTTPException(404,"Job not found")
        if j.status not in ("failed","dispatch_failed","cancelled"):
            raise HTTPException(409,"Only failed or cancelled jobs can be retried")
        j.status="queued"
        j.cancel_requested=False
        j.progress=0
        j.stage="queued for retry"
        j.timings=None
        log_event(j.id,"job","Retry requested",by=actor_label(actor))
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
        if job is None or job.deleted_at is not None or job.status!="completed" or not job.output_key:
            raise HTTPException(404,"Video not available")
        try:
            check_playback_token(token,job_id,job.owner_user_id,settings.auth_session_secret)
        except InvalidPlaybackToken as exc:
            raise HTTPException(403,"Playback grant expired or invalid") from exc
        return job.output_key,job.subtitle_key

@app.get("/api/jobs/{job_id}/preview")
def preview_video(job_id:str,request:Request,token:str=Query(min_length=20,max_length=2048),download:bool=False):
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
             "Content-Disposition":(f'attachment; filename="{job_id}.mp4"' if download else "inline"),
             "Cache-Control":"private, no-store",
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
