import hashlib
import uuid
from contextlib import contextmanager
from fastapi import FastAPI,UploadFile,File,Depends,HTTPException,Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from sqlalchemy import select,text
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

@app.get("/api/jobs",dependencies=[Depends(authorize)])
def list_jobs():
    with session() as db:
        jobs=db.scalars(select(TranslationJob).order_by(TranslationJob.created_at.desc()).limit(100)).all()
        return [{"id":j.id,"status":j.status,"source_lang":j.source_lang,"target_lang":j.target_lang,"created_at":j.created_at.isoformat()} for j in jobs]

@app.get("/api/jobs/{job_id}",dependencies=[Depends(authorize)])
def get_job(job_id:str):
    with session() as db:
        j=db.get(TranslationJob,job_id)
        if j is None:raise HTTPException(404,"Not found")
        return {"id":j.id,"status":j.status,"source_lang":j.source_lang,"target_lang":j.target_lang,"transcript":j.transcript,"translation":j.translation,"error":j.error,"has_output":bool(j.output_key),"mode":settings.model_mode}

@app.get("/api/jobs/{job_id}/download",dependencies=[Depends(authorize)])
def download(job_id:str):
    with session() as db:
        j=db.get(TranslationJob,job_id)
        if not j or not j.output_key:raise HTTPException(404,"Output not found")
        key=j.output_key
    try:response=client().get_object(Bucket=settings.minio_bucket,Key=key)
    except Exception as exc:raise HTTPException(502,"Storage unavailable") from exc
    return StreamingResponse(response["Body"].iter_chunks(chunk_size=1024*1024),media_type="video/mp4",headers={"Content-Disposition":f'attachment; filename="{job_id}.mp4"'})
