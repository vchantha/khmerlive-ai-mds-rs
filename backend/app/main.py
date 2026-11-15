import hashlib
import uuid
from contextlib import contextmanager
from fastapi import FastAPI,UploadFile,File,Depends,HTTPException,Header,Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from sqlalchemy import select,text,func,or_
from app.db import SessionLocal
from app.models import MediaAsset,TranslationJob
from app.storage import client
from app.config import settings
from app.tasks import translate_media

app=FastAPI(title="KhmerLive AI — Research MVP",version="0.1.0")

def authorize(x_api_key:str|None=Header(default=None)):
    if not x_api_key or x_api_key!=settings.api_key:
        raise HTTPException(status_code=401,detail="Invalid API key")

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
    return {"mode":settings.model_mode,"genuine_translation_available":False,"note":"Demo-only pipeline. No real Khmer ASR/MT/TTS is bundled."}

@app.post("/api/media",status_code=201,dependencies=[Depends(authorize)])
async def upload(file:UploadFile=File(...)):
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
        obj=MediaAsset(id=mid,filename=name,object_key=key,content_type="video/mp4",size_bytes=size,sha256=digest.hexdigest())
        db.add(obj);db.commit()
    return {"media_id":mid,"size_bytes":size,"sha256":digest.hexdigest()}

class JobCreate(BaseModel):
    media_id:str
    source_lang:str=Field(pattern="^(en|km)$")
    target_lang:str=Field(pattern="^(en|km)$")

@app.post("/api/jobs",status_code=202,dependencies=[Depends(authorize)])
def create_job(payload:JobCreate):
    if payload.source_lang==payload.target_lang:raise HTTPException(422,"Language pair must differ")
    with session() as db:
        if db.get(MediaAsset,payload.media_id) is None:raise HTTPException(404,"Media not found")
        jid=str(uuid.uuid4())
        job=TranslationJob(id=jid,media_id=payload.media_id,source_lang=payload.source_lang,target_lang=payload.target_lang,status="queued")
        db.add(job);db.commit()
    try:translate_media.delay(jid)
    except Exception as exc:
        with session() as db:
            job=db.get(TranslationJob,jid);job.status="dispatch_failed";job.error="Queue dispatch failed";db.commit()
        raise HTTPException(503,"Queue temporarily unavailable") from exc
    return {"job_id":jid,"status":"queued","mode":settings.model_mode}

def format_job(job,media):
    return {
        "id":job.id,"media_id":job.media_id,"filename":media.filename,
        "size_bytes":media.size_bytes,"status":job.status,
        "progress":job.progress or 0,"stage":job.stage,"cancel_requested":bool(job.cancel_requested),
        "source_lang":job.source_lang,"target_lang":job.target_lang,
        "created_at":job.created_at.isoformat() if job.created_at else None,
        "updated_at":job.updated_at.isoformat() if job.updated_at else None,
        "transcript":job.transcript,"translation":job.translation,
        "error":job.error,"has_output":bool(job.output_key),"mode":settings.model_mode,
    }

@app.get("/api/dashboard",dependencies=[Depends(authorize)])
def dashboard():
    with session() as db:
        rows=db.execute(select(TranslationJob.status,func.count(TranslationJob.id)).group_by(TranslationJob.status)).all()
        counts=dict(rows)
    return {"total":sum(counts.values()),"queued":counts.get("queued",0),
        "processing":counts.get("processing",0),"completed":counts.get("completed",0),
        "failed":counts.get("failed",0)+counts.get("dispatch_failed",0),
        "by_status":counts,"mode":settings.model_mode}

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
              status:str|None=Query(None),search:str|None=Query(None,max_length=200)):
    with session() as db:
        q=select(TranslationJob,MediaAsset).join(MediaAsset,TranslationJob.media_id==MediaAsset.id)
        if status and status!="all":
            if status=="failed":q=q.where(TranslationJob.status.in_(["failed","dispatch_failed"]))
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
def get_job(job_id:str):
    with session() as db:
        row=db.execute(select(TranslationJob,MediaAsset).join(MediaAsset,TranslationJob.media_id==MediaAsset.id).where(TranslationJob.id==job_id)).first()
        if row is None:raise HTTPException(404,"Not found")
        return format_job(*row)


@app.post("/api/jobs/{job_id}/cancel",dependencies=[Depends(authorize)])
def cancel_job(job_id:str):
    with session() as db:
        j=db.scalar(select(TranslationJob).where(TranslationJob.id==job_id).with_for_update())
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
def retry_job(job_id:str):
    with session() as db:
        j=db.scalar(select(TranslationJob).where(TranslationJob.id==job_id).with_for_update())
        if j is None:raise HTTPException(404,"Job not found")
        if j.status not in ("failed","dispatch_failed","cancelled"):
            raise HTTPException(409,"Only failed or cancelled jobs can be retried")
        j.status="queued"
        j.cancel_requested=False
        j.progress=0
        j.stage="queued for retry"
        j.error=None
        j.output_key=None
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

@app.get("/api/jobs/{job_id}/download",dependencies=[Depends(authorize)])
def download(job_id:str):
    with session() as db:
        j=db.get(TranslationJob,job_id)
        if not j or not j.output_key:raise HTTPException(404,"Output not found")
        key=j.output_key
    try:response=client().get_object(Bucket=settings.minio_bucket,Key=key)
    except Exception as exc:raise HTTPException(502,"Storage unavailable") from exc
    return StreamingResponse(response["Body"].iter_chunks(chunk_size=1024*1024),media_type="video/mp4",headers={"Content-Disposition":f'attachment; filename="{job_id}.mp4"'})
