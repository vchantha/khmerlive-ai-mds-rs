import os
import subprocess
import tempfile
from pathlib import Path
from celery import Celery
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import TranslationJob,MediaAsset
from app.storage import client
from app.adapters import get_adapters
celery_app=Celery("khmerlive",broker=settings.redis_url,backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True,worker_prefetch_multiplier=1,task_track_started=True,task_serializer="json",accept_content=["json"],task_time_limit=600)

def set_state(db,job,status,error=None):
    job.status=status
    job.error=error
    db.commit()

@celery_app.task(name="translate_media",bind=True)
def translate_media(self,job_id:str):
    with SessionLocal() as db:
        job=db.get(TranslationJob,job_id)
        if job is None:return
        if job.status=="completed":return
        set_state(db,job,"processing")
        media=db.get(MediaAsset,job.media_id)
        try:
            asr,mt=get_adapters()
            with tempfile.TemporaryDirectory() as td:
                root=Path(td)
                source=root/"input.mp4"
                audio=root/"input.wav"
                result=root/"output.mp4"
                s3=client()
                s3.download_file(settings.minio_bucket,media.object_key,str(source))
                subprocess.run(["ffmpeg","-v","error","-nostdin","-y","-i",str(source),"-map","0:a:0","-vn","-ac","1","-ar","16000",str(audio)],check=True,timeout=120)
                text=asr.transcribe(audio,job.source_lang).text
                translated=mt.translate(text,job.source_lang,job.target_lang)
                # DEMO MODE: pass video through, do not pretend audio has been dubbed.
                subprocess.run(["ffmpeg","-v","error","-nostdin","-y","-i",str(source),"-map","0:v:0?","-map","0:a:0?","-c","copy",str(result)],check=True,timeout=120)
                key=f"outputs/{job.id}.mp4"
                s3.upload_file(str(result),settings.minio_bucket,key,ExtraArgs={"ContentType":"video/mp4"})
                job.transcript=text
                job.translation=translated
                job.output_key=key
                set_state(db,job,"completed")
        except Exception as exc:
            db.rollback()
            set_state(db,job,"failed",str(exc)[:1500])
            raise
