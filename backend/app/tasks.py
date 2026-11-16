import hashlib
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
from app.real_inference import translate_audio, build_srt, TimedText
from app.khmer_tts import build_dubbed_audio
from app.live_capture import capture_chunks,combine_chunks
from app.stream_urls import validate_stream_url
from app.youtube import download_youtube,youtube_video_id,safe_title
celery_app=Celery("khmerlive",broker=settings.redis_url,backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True,worker_prefetch_multiplier=1,task_track_started=True,task_serializer="json",accept_content=["json"],task_time_limit=settings.job_time_limit_seconds,task_soft_time_limit=max(60,settings.job_time_limit_seconds-300))

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
    with SessionLocal() as db:
        job=db.get(TranslationJob,job_id)
        if job is None:return
        if job.status!="queued":return
        check_cancel(db,job)
        set_state(db,job,"processing",progress=5,stage="starting")
        media=db.get(MediaAsset,job.media_id)
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
                                chunk_rows=translate_audio(piece_audio,job.source_lang,job.target_lang,
                                    settings.whisper_model_path,settings.translation_model_path,
                                    settings.inference_device,settings.asr_cpu_threads)
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
                    set_state(db,job,"processing",progress=25,stage="extracting audio")
                    subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
                        "-i",str(source),"-map","0:a:0","-vn","-ac","1",
                        "-ar","16000",str(audio)],check=True,timeout=600)
                    check_cancel(db,job)
                    if mode=="real_subtitles":
                        set_state(db,job,"processing",progress=45,stage="recognizing and translating speech")
                        rows=translate_audio(audio,job.source_lang,job.target_lang,
                                             settings.whisper_model_path,
                                             settings.translation_model_path,
                                             settings.inference_device,settings.asr_cpu_threads)
                        text=" ".join(row.source_text for row in rows)
                        translated=" ".join(row.target_text for row in rows)
                        subtitle_path.write_text(build_srt(rows),encoding="utf-8")
                        rows_for_dubbing=rows
                    else:
                        set_state(db,job,"processing",progress=45,stage="demo transcription")
                        text=asr.transcribe(audio,job.source_lang).text
                        translated=mt.translate(text,job.source_lang,job.target_lang)
                check_cancel(db,job)
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
                        set_state(db,job,"processing",progress=70,stage="synthesizing Khmer voice")
                        dubbed=root/"khmer-dub.wav"
                        build_dubbed_audio(rows_for_dubbing or [],dubbed,clip_seconds,
                                           settings.khmer_tts_model_path,settings.inference_device)
                        check_cancel(db,job)
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
                set_state(db,job,"completed",progress=100,stage="completed")
        except CancelledJob:
            return
        except Exception as exc:
            db.rollback()
            set_state(db,job,"failed",str(exc)[:1500],stage="failed")
            raise
