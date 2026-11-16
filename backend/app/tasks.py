import hashlib
import json
import logging
import os
import signal
import subprocess
import tempfile
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from celery import Celery
from celery.signals import worker_process_init,worker_ready
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import TranslationJob,MediaAsset
from app.storage import client
from app.adapters import get_adapters
from app.real_inference import translate_audio, build_srt, TimedText
from app.khmer_tts import build_dubbed_audio
from app.llm_postedit import postedit_rows,unload_llm,preload_llm
from app.joblog import log_event,log_llm_tasks
from app.live_capture import capture_chunks,combine_chunks
from app.stream_urls import validate_stream_url
from app.youtube import download_youtube,youtube_video_id,safe_title
celery_app=Celery("khmerlive",broker=settings.redis_url,backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True,worker_prefetch_multiplier=1,task_track_started=True,task_serializer="json",accept_content=["json"],task_time_limit=settings.job_time_limit_seconds,task_soft_time_limit=max(60,settings.job_time_limit_seconds-300),
                       worker_max_tasks_per_child=settings.worker_max_tasks_per_child or None)
logger=logging.getLogger(__name__)
ACTIVE=("processing","cancelling")


@worker_process_init.connect
def _limit_threads(**_):
    """Give each prefork process its share of the CPU so parallel jobs don't oversubscribe cores."""
    threads=settings.threads_per_job()
    for var in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS"):
        os.environ[var]=str(threads)
    try:
        import torch
        torch.set_num_threads(threads)
        torch.set_num_interop_threads(1)
    except Exception:
        pass   # demo image has no torch
    signal.signal(signal.SIGTERM,_on_sigterm)
    logger.info("Worker process: %d CPU threads per job; devices asr=%s mt=%s tts=%s",
                threads,settings.device_for("asr"),settings.device_for("mt"),settings.device_for("tts"))


def recover_interrupted_jobs(active_job_ids:set[str]|None)->int:
    """Fail jobs left 'processing' by a worker that died (restart, crash, OOM) so users can Retry.

    active_job_ids: job ids running on live workers, or None if they couldn't be listed;
    then only jobs older than the hard time limit (certainly dead) are recovered.
    """
    cutoff=datetime.now(timezone.utc)-timedelta(seconds=settings.job_time_limit_seconds+120)
    with SessionLocal() as db:
        q=select(TranslationJob).where(TranslationJob.status.in_(ACTIVE))
        if active_job_ids is None:q=q.where(TranslationJob.updated_at<cutoff)
        elif active_job_ids:q=q.where(TranslationJob.id.not_in(active_job_ids))
        stuck=db.scalars(q.with_for_update()).all()
        n=0
        for job in stuck:
            job.status="failed" if job.status=="processing" else "cancelled"
            job.stage="interrupted" if job.status=="failed" else "cancelled"
            job.error="Interrupted: the worker stopped while processing (for example a restart). Retry the job." if job.status=="failed" else None
            n+=1
        db.commit()
    if n:logger.warning("Recovered %d interrupted job(s)",n)
    return n


@worker_ready.connect
def _recover_on_start(sender=None,**_):
    active:set[str]|None=set()
    try:
        replies=celery_app.control.inspect(timeout=2).active() or {}
        for host,tasks in replies.items():
            if sender is not None and host==getattr(sender,"hostname",None):continue
            for t in tasks:
                args=t.get("args") or []
                if args:active.add(str(args[0]))
    except Exception as exc:
        logger.warning("Could not list active tasks (%s); only recovering jobs past the time limit",exc)
        active=None
    try:recover_interrupted_jobs(active)
    except Exception as exc:logger.warning("Interrupted-job recovery failed: %s",exc)
    if settings.llm_preload_on_start and settings.llm_postedit_enabled:
        import threading
        threading.Thread(target=preload_llm,name="llm-preload",daemon=True).start()


STAGE_LABELS={"prepare":"Prepare","download":"Get source video","extract_audio":"Extract audio",
              "asr_translate":"Speech recognition + translation","llm_postedit":"LLM post-editing",
              "tts":"Khmer voice synthesis","mux":"Build video (mux)","upload":"Publish output"}

class StageClock:
    """Wall-clock seconds per pipeline stage (saved on the job) and a step log (job_events)."""
    def __init__(self,job_id:str|None=None):
        self.data:dict={};self._t=time.monotonic();self._start=self._t;self._stage=None
        self.job_id=job_id;self._notes:dict={}
    def note(self,**details):
        """Attach details to the current stage's 'finished' log event."""
        self._notes.update(details)
    def mark(self,stage:str|None):
        now=time.monotonic()
        if self._stage:
            self.data[self._stage]=round(self.data.get(self._stage,0)+now-self._t,2)
            if self.job_id:
                log_event(self.job_id,self._stage,"Finished: "+STAGE_LABELS.get(self._stage,self._stage),
                          seconds=now-self._t,**self._notes)
        self._notes={}
        if stage and self.job_id:
            log_event(self.job_id,stage,"Started: "+STAGE_LABELS.get(stage,stage))
        self._stage,self._t=stage,now
    def finish(self)->dict:
        self.mark(None);self.data["total"]=round(time.monotonic()-self._start,2);return self.data

def inference_kwargs(timings:dict)->dict:
    asr=settings.device_for("asr")
    return dict(mt_device=settings.device_for("mt"),asr_compute=settings.asr_compute_type,
                mt_engine=settings.mt_engine,mt_ct2_dir=settings.mt_ct2_path,beam_size=settings.mt_beam_size,
                timings=timings,keep_asr_loaded=not(asr=="cuda" and (settings.asr_release_after_use or settings.llm_unload_before_gpu_asr)))

def free_gpu_for_asr():
    if settings.device_for("asr")=="cuda" and settings.llm_unload_before_gpu_asr:
        unload_llm()

def output_codec_args(source:Path)->list[str]:
    """Stream-copy when the input is already browser-playable (H.264 yuv420p + AAC).

    Re-encoding a long, already-compatible video with libx264 costs minutes of
    CPU and adds nothing; only transcode streams that actually need it.
    """
    import json
    probed=subprocess.run(["ffprobe","-v","error","-show_entries",
        "stream=codec_type,codec_name,pix_fmt","-of","json",str(source)],
        check=True,capture_output=True,text=True,timeout=30)
    streams=json.loads(probed.stdout).get("streams",[])
    video=next((s for s in streams if s.get("codec_type")=="video"),None)
    audio=next((s for s in streams if s.get("codec_type")=="audio"),None)
    if video and video.get("codec_name")=="h264" and video.get("pix_fmt")=="yuv420p":
        vargs=["-c:v","copy"]
    else:
        vargs=["-c:v","libx264","-preset","veryfast","-crf","23","-pix_fmt","yuv420p"]
    if audio is None or audio.get("codec_name")=="aac":
        aargs=["-c:a","copy"]
    else:
        aargs=["-c:a","aac","-b:a","128k"]
    return vargs+aargs

class CancelledJob(Exception):
    pass

class JobAborted(BaseException):
    """Raised by the SIGTERM handler when the API terminates a running job.

    BaseException so broad `except Exception` blocks inside stages can't swallow it;
    unwinding kills child processes (subprocess.run) and removes the temp directory.
    """

_running_job:str|None=None

def _on_sigterm(signum,frame):
    if _running_job:
        raise JobAborted()
    # Idle process: behave like the default SIGTERM (exit).
    signal.signal(signal.SIGTERM,signal.SIG_DFL)
    os.kill(os.getpid(),signal.SIGTERM)

def check_cancel(db,job):
    db.refresh(job)
    if job.cancel_requested or job.status in ("cancelled","cancelling"):
        job.status="cancelled"
        job.stage="cancelled"
        db.commit()
        raise CancelledJob()

def set_state(db,job,status,error=None,progress=None,stage=None):
    job.status=status
    job.error=error
    if progress is not None:job.progress=progress
    if stage is not None:job.stage=stage
    db.commit()

def persist_captured(s3,db,media,source:Path):
    """Store downloaded/captured media so retries replay it instead of re-fetching."""
    if not source.exists() or source.stat().st_size<1024:
        raise RuntimeError("Source yielded no playable MP4")
    s3.upload_file(str(source),settings.minio_bucket,media.object_key,ExtraArgs={"ContentType":"video/mp4"})
    digest=hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    media.sha256=digest.hexdigest()
    media.size_bytes=source.stat().st_size
    db.commit()

@celery_app.task(name="translate_media",bind=True)
def translate_media(self,job_id:str):
    global _running_job
    _running_job=job_id
    try:
        return _translate_media(job_id)
    except JobAborted:
        _finish_aborted(job_id)
    finally:
        _running_job=None

def _finish_aborted(job_id:str):
    """Terminated mid-stage: Cancelled if the user asked for it, otherwise Interrupted."""
    with SessionLocal() as db:
        job=db.get(TranslationJob,job_id)
        if job is None or job.status in ("completed","failed","cancelled"):return
        if job.cancel_requested or job.status=="cancelling":
            job.status,job.stage,job.error="cancelled","cancelled",None
        else:
            job.status,job.stage="failed","interrupted"
            job.error="Interrupted: the worker stopped while processing. Retry the job."
        db.commit()
        status=job.status
    log_event(job_id,"job","Stopped immediately: cancelled by user" if status=="cancelled"
              else "Interrupted: the worker was stopped",level="warning")

def _translate_media(job_id:str):
    with SessionLocal() as db:
        job=db.get(TranslationJob,job_id)
        if job is None:return
        if job.status!="queued":return
        check_cancel(db,job)
        set_state(db,job,"processing",progress=5,stage="starting")
        media=db.get(MediaAsset,job.media_id)
        log_event(job.id,"job","Job started",mode=job.processing_mode,source=media.source_kind,
                  file=media.filename,languages=f"{job.source_lang}->{job.target_lang}",
                  devices={k:settings.device_for(k) for k in ("asr","mt","tts")},cpu_threads=settings.threads_per_job())
        clock=StageClock(job.id);clock.mark("prepare")
        timings:dict={}
        try:
            mode=job.processing_mode
            if mode not in ("demo","real_subtitles"):
                raise ValueError("Unsupported processing mode: "+mode)
            if mode=="demo":
                asr,mt=get_adapters()
            with tempfile.TemporaryDirectory() as td:
                root=Path(td)
                source=root/"input.mp4"
                audio=root/"input.wav"
                result=root/"output.mp4"
                s3=client()
                streamed_rows=None
                clock.mark("download")
                if media.source_kind=="youtube":
                    check_cancel(db,job)
                    set_state(db,job,"processing",progress=10,stage="downloading YouTube video")
                    video_id=youtube_video_id(media.source_url)
                    info=download_youtube(video_id,source,
                        settings.max_video_duration_seconds,settings.max_upload_mb*1024*1024)
                    name=safe_title(info.get("title"),"YouTube "+video_id)
                    original=info.get("duration")
                    if original and original>settings.max_video_duration_seconds:
                        # Long video: only the first section was downloaded. Record it.
                        media.capture_seconds=settings.max_video_duration_seconds
                        name+=" (first "+str(round(settings.max_video_duration_seconds/60))+\
                            " of "+str(round(original/60))+" min)"
                    media.filename=name[:250]+".mp4"
                    persist_captured(s3,db,media,source)
                elif media.source_kind=="url":
                    check_cancel(db,job)
                    set_state(db,job,"processing",progress=10,stage="capturing URL stream")
                    # Restrict URL schemes, user-configured allowed hosts, and public DNS.
                    validate_stream_url(media.source_url)
                    seconds=int(media.capture_seconds or 30)
                    if mode=="real_subtitles":
                        # FFmpeg records while the model translates each *closed* chunk.
                        # Updates are committed to PostgreSQL so the UI can poll partial
                        # live captions without waiting for the whole recording.
                        streamed_rows=[]
                        chunkdir=root/"stream-chunks"
                        def _cancel():
                            check_cancel(db,job)
                        for part,offset_ms in capture_chunks(media.source_url,seconds,chunkdir,_cancel):
                            check_cancel(db,job)
                            piece_audio=root/("stream-"+part.stem+".wav")
                            subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
                                "-i",str(part),"-map","0:a:0","-vn","-ac","1",
                                "-ar","16000",str(piece_audio)],check=True,timeout=90)
                            try:
                                free_gpu_for_asr()
                                chunk_rows=translate_audio(piece_audio,job.source_lang,job.target_lang,
                                    settings.whisper_model_path,settings.translation_model_path,
                                    settings.device_for("asr"),settings.threads_per_job(),**inference_kwargs(timings))
                            except ValueError as exc:
                                if "No intelligible speech" not in str(exc):
                                    raise
                                chunk_rows=[]
                            streamed_rows.extend(TimedText(
                                start_ms=offset_ms+row.start_ms,end_ms=offset_ms+row.end_ms,
                                source_text=row.source_text,target_text=row.target_text)
                                for row in chunk_rows)
                            job.transcript=" ".join(s.source_text for s in streamed_rows)
                            job.translation=" ".join(s.target_text for s in streamed_rows)
                            set_state(db,job,"processing",
                                progress=min(68,max(15,round((offset_ms+10000)*65/(seconds*1000)))),
                                stage="stream translated "+str(len(streamed_rows))+" speech segments")
                        combine_chunks(chunkdir,source)
                        if not streamed_rows:
                            raise ValueError("No intelligible speech found in the stream")
                    else:
                        cmd=["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y",
                             "-rw_timeout","15000000",
                             "-protocol_whitelist","http,https,tcp,tls,crypto",
                             "-i",media.source_url,
                             "-t",str(seconds),
                             "-map","0:v:0?","-map","0:a:0?",
                             "-c:v","libx264","-preset","ultrafast",
                             "-pix_fmt","yuv420p","-c:a","aac",
                             "-movflags","+faststart","-fs",str(1024*1024*1024),
                             str(source)]
                        subprocess.run(cmd,check=True,timeout=max(100,seconds*4+60))
                    persist_captured(s3,db,media,source)
                else:
                    s3.download_file(settings.minio_bucket,media.object_key,str(source))
                check_cancel(db,job)
                clock.note(source=media.source_kind,size_mb=round(source.stat().st_size/1048576,1))
                if source.stat().st_size>settings.max_upload_mb*1024*1024:
                    raise ValueError("Captured media exceeds configured MAX_UPLOAD_MB")
                import json
                metadata=subprocess.run(["ffprobe","-v","error",
                    "-show_entries","format=duration","-of","json",str(source)],
                    capture_output=True,text=True,check=True,timeout=30)
                clip_seconds=float(json.loads(metadata.stdout)["format"]["duration"])
                if clip_seconds>settings.max_video_duration_seconds:
                    raise ValueError("Video is too long for this worker: "+
                        str(round(clip_seconds))+" seconds (limit "+
                        str(settings.max_video_duration_seconds)+"s)")
                subtitle_path=root/"translated.srt"
                rows_for_dubbing=None
                if streamed_rows is not None:
                    # The streaming URL path has already produced real captions.
                    text=" ".join(row.source_text for row in streamed_rows)
                    translated=" ".join(row.target_text for row in streamed_rows)
                    subtitle_path.write_text(build_srt(streamed_rows),encoding="utf-8")
                    rows_for_dubbing=streamed_rows
                else:
                    clock.mark("extract_audio")
                    set_state(db,job,"processing",progress=25,stage="extracting audio")
                    subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
                        "-i",str(source),"-map","0:a:0","-vn","-ac","1",
                        "-ar","16000",str(audio)],check=True,timeout=600)
                    check_cancel(db,job)
                    if mode=="real_subtitles":
                        clock.mark("asr_translate")
                        set_state(db,job,"processing",progress=45,stage="recognizing and translating speech")
                        free_gpu_for_asr()
                        rows=translate_audio(audio,job.source_lang,job.target_lang,
                                             settings.whisper_model_path,
                                             settings.translation_model_path,
                                             settings.device_for("asr"),settings.threads_per_job(),
                                             **inference_kwargs(timings))
                        text=" ".join(row.source_text for row in rows)
                        translated=" ".join(row.target_text for row in rows)
                        subtitle_path.write_text(build_srt(rows),encoding="utf-8")
                        rows_for_dubbing=rows
                        clock.note(segments=len(rows),asr_seconds=timings.get("asr"),translate_seconds=timings.get("translate"),
                                   asr_device=settings.device_for("asr"),mt_device=settings.device_for("mt"),
                                   mt_engine=timings.get("mt_engine"),media_seconds=round(clip_seconds,1))
                    else:
                        set_state(db,job,"processing",progress=45,stage="demo transcription")
                        text=asr.transcribe(audio,job.source_lang).text
                        translated=mt.translate(text,job.source_lang,job.target_lang)
                if mode=="real_subtitles" and rows_for_dubbing is not None:
                    check_cancel(db,job)
                    if (settings.llm_postedit_enabled or settings.vllm_postedit_enabled) and job.source_lang=="en" and job.target_lang=="km":
                        clock.mark("llm_postedit")
                        set_state(db,job,"processing",progress=60,stage="offline LLM translation post-editing")
                        llm_tasks:list=[]
                        rows_for_dubbing=postedit_rows(rows_for_dubbing,job.source_lang,job.target_lang,report=llm_tasks)
                        log_llm_tasks(job.id,llm_tasks)
                        counts={}
                        for t in llm_tasks:counts[t["status"]]=counts.get(t["status"],0)+1
                        clock.note(model=settings.llm_model if settings.llm_postedit_enabled else settings.vllm_model,
                                   lines=len(llm_tasks),results=counts,parallel=settings.llm_concurrency)
                        translated=" ".join(row.target_text for row in rows_for_dubbing)
                        subtitle_path.write_text(build_srt(rows_for_dubbing),encoding="utf-8")
                check_cancel(db,job)
                clock.mark("mux")
                set_state(db,job,"processing",progress=65,stage="muxing subtitles" if mode=="real_subtitles" else "remuxing demo video")
                codec_args=output_codec_args(source)
                # Reuse the duration probed above; transcodes scale with length.
                mux_timeout=max(1800,int(clip_seconds*1.5))
                if mode=="real_subtitles":
                    # EN→KM voice dub: replace the original English audio, never mix
                    # it back in or silently claim a translated voice.
                    dubbing=settings.enable_khmer_dubbing and job.target_lang=="km"
                    audio_args=[]
                    if dubbing:
                        clock.mark("tts")
                        set_state(db,job,"processing",progress=70,stage="synthesizing Khmer voice")
                        dubbed=root/"khmer-dub.wav"
                        placement:dict={}
                        build_dubbed_audio(rows_for_dubbing or [],dubbed,clip_seconds,
                                           settings.khmer_tts_model_path,settings.device_for("tts"),stats_out=placement)
                        clock.note(device=settings.device_for("tts"),lines=sum(placement.values()),placement=placement)
                        check_cancel(db,job)
                        clock.mark("mux")
                        audio_args=["-i",str(dubbed)]
                    cmd=["ffmpeg","-v","error","-nostdin","-y",
                         "-i",str(source),"-i",str(subtitle_path),*audio_args,
                         "-map","0:v:0","-map",("2:a:0" if dubbing else "0:a:0?"),
                         "-map","1:0",*codec_args]
                    if dubbing:
                        # Force AAC encoding even if source audio is AAC.
                        cmd.extend(["-c:a","aac","-b:a","160k"])
                    cmd.extend(["-c:s","mov_text",
                        "-metadata:s:s:0","language="+("khm" if job.target_lang=="km" else "eng"),
                        "-disposition:s:0","default","-movflags","+faststart",
                        str(result)])
                    subprocess.run(cmd,check=True,timeout=mux_timeout)
                else:
                    # DEMO ONLY. No translation or dubbing.
                    subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
                        "-i",str(source),"-map","0:v:0?","-map","0:a:0?",
                        *codec_args,
                        "-movflags","+faststart",str(result)],check=True,timeout=mux_timeout)
                # Verify output is a valid MP4 with browser-decodable H.264 video.
                import json
                probed=subprocess.run(["ffprobe","-v","error","-show_entries",
                    "stream=codec_name,codec_type","-of","json",str(result)],
                    check=True,capture_output=True,text=True,timeout=30)
                tracks=json.loads(probed.stdout).get("streams",[])
                if not any(s.get("codec_type")=="video" and s.get("codec_name")=="h264" for s in tracks):
                    raise RuntimeError("Playable H.264 video stream was not created")
                if mode=="real_subtitles" and not any(s.get("codec_type")=="subtitle" and s.get("codec_name")=="mov_text" for s in tracks):
                    raise RuntimeError("Translated subtitle stream was not attached to the MP4")
                if mode=="real_subtitles" and settings.enable_khmer_dubbing and job.target_lang=="km":
                    if not any(s.get("codec_type")=="audio" and s.get("codec_name")=="aac" for s in tracks):
                        raise RuntimeError("Khmer-dubbed AAC audio stream was not created")
                key=(f"outputs/{job.id}.khmer-dubbed.mp4" if mode=="real_subtitles" and settings.enable_khmer_dubbing and job.target_lang=="km" else f"outputs/{job.id}.mp4")
                check_cancel(db,job)
                clock.mark("upload")
                set_state(db,job,"processing",progress=85,stage="publishing output")
                s3.upload_file(str(result),settings.minio_bucket,key,ExtraArgs={"ContentType":"video/mp4"})
                check_cancel(db,job)
                if mode=="real_subtitles":
                    subtitle_key=f"outputs/{job.id}.srt"
                    s3.upload_file(str(subtitle_path),settings.minio_bucket,subtitle_key,
                                   ExtraArgs={"ContentType":"application/x-subrip"})
                    job.subtitle_key=subtitle_key
                job.transcript=text
                job.translation=translated
                job.output_key=key
                stages=clock.finish()
                if "asr_translate" in stages and "asr" in timings:
                    # Split the combined stage using the engines' own measurements.
                    stages.pop("asr_translate")
                    stages["asr"]=timings["asr"];stages["translate"]=timings.get("translate",0)
                info={"seconds":stages,"media_seconds":round(clip_seconds,1),"segments":timings.get("segments"),
                      "mt_engine":timings.get("mt_engine"),"devices":{k:settings.device_for(k) for k in ("asr","mt","tts")},
                      "cpu_threads":settings.threads_per_job()}
                job.timings=json.dumps(info)
                logger.info("Job %s finished in %.1fs for %.0fs of media: %s",job.id,stages["total"],clip_seconds,stages)
                set_state(db,job,"completed",progress=100,stage="completed")
                log_event(job.id,"job","Job completed",seconds=stages["total"],stages=stages,
                          media_seconds=round(clip_seconds,1),output=key)
        except CancelledJob:
            log_event(job.id,"job","Cancelled by user",level="warning")
            return
        except Exception as exc:
            db.rollback()
            set_state(db,job,"failed",str(exc)[:1500],stage="failed")
            log_event(job.id,clock._stage or "job","Failed: "+str(exc)[:500],level="error",error_type=type(exc).__name__)
            raise
