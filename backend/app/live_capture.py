"""Incremental bounded HTTP(S) video capture for near-live subtitle updates.

Records a finite number of seconds from approved URL, yielding *closed*
segments as FFmpeg records further segments. Inference can lag capture.
This is neither WebRTC nor guaranteed real-time simultaneous translation.
URL validation and egress restrictions remain necessary at the network layer.
"""
import json
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterator

def duration_ms(path:Path)->int:
    r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","json",str(path)],check=True,text=True,capture_output=True,timeout=30)
    ms=round(float(json.loads(r.stdout)["format"]["duration"])*1000)
    if ms<=0:raise ValueError("Captured segment has no duration")
    return ms

def segment_command(url:str,seconds:int,out_dir:Path,chunk_seconds:int=12)->list[str]:
    if not 5<=seconds<=120:raise ValueError("Duration 5–120 seconds only")
    if not 2<=chunk_seconds<=30:raise ValueError("Chunk duration 2–30 seconds only")
    out_dir.mkdir(parents=True,exist_ok=True)
    return ["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y",
        "-rw_timeout","15000000",
        "-protocol_whitelist","http,https,tcp,tls,crypto",
        "-i",url,"-t",str(seconds),
        "-map","0:v:0","-map","0:a:0?",
        "-c:v","libx264","-preset","ultrafast","-crf","26",
        "-pix_fmt","yuv420p","-force_key_frames",f"expr:gte(t,n_forced*{chunk_seconds})",
        "-c:a","aac","-b:a","96k",
        "-f","segment","-segment_time",str(chunk_seconds),
        "-reset_timestamps","1",str(out_dir/"chunk_%04d.mp4")]

def capture_chunks(url:str,seconds:int,out_dir:Path,check_cancel:Callable[[],None],
                   chunk_seconds:int=12)->Iterator[tuple[Path,int]]:
    """Yield segment file and approximate playback offset in milliseconds.

    A segment is considered closed after FFmpeg starts writing the next
    segment, or when FFmpeg exits. Live subtitles can be published as soon
    as each closed chunk finishes local ASR/translation inference.
    """
    cmd=segment_command(url,seconds,out_dir,chunk_seconds)
    proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    emitted=0
    offset_ms=0
    deadline=time.monotonic()+max(150,seconds+75)
    try:
        while True:
            check_cancel()
            if time.monotonic()>deadline:
                raise TimeoutError("Stream capture exceeded its time limit")
            finished=proc.poll() is not None
            files=sorted(out_dir.glob("chunk_*.mp4"))
            ready=files if finished else files[:-1]
            while emitted<len(ready):
                path=ready[emitted]
                if path.stat().st_size<1024:
                    raise ValueError("Empty media segment")
                ms=duration_ms(path)
                yield path,offset_ms
                offset_ms+=ms
                emitted+=1
            if finished:break
            time.sleep(0.35)
        if proc.returncode!=0:
            raise RuntimeError("FFmpeg could not capture the URL stream (check source, formats and access)")
        if not emitted:
            raise RuntimeError("Stream did not yield media segments")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait(timeout=5)

def combine_chunks(directory:Path,destination:Path)->None:
    parts=sorted(directory.glob("chunk_*.mp4"))
    if not parts:raise ValueError("No captured media segments")
    listing=directory/"concat.txt"
    # segment files are generated with trusted names within workdir
    listing.write_text("".join("file '"+p.name+"'\n" for p in parts),encoding="utf-8")
    subprocess.run(["ffmpeg","-v","error","-nostdin","-y","-f","concat","-safe","0",
        "-i",str(listing),"-c","copy","-movflags","+faststart",str(destination)],
        check=True,timeout=120)
    if not destination.is_file() or destination.stat().st_size<1024:
        raise RuntimeError("Concatenated stream produced no video")
