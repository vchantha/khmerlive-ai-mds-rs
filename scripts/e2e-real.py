#!/usr/bin/env python3
"""Real-model end-to-end integration check with real user-provided spoken media.

Requires local model files, real_subtitles mode, approved URL (if used), and
a running Compose stack. This is not a translation accuracy certification.
"""
import argparse
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

def key():
    if os.getenv("API_KEY"):return os.environ["API_KEY"]
    env=Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("API_KEY="):return line.split("=",1)[1].strip().strip('"')
    raise RuntimeError("API_KEY not set and no .env found")

def get(base,path,*,data=None,content_type=None,range_header=None):
    headers={"X-API-Key":key()}
    if content_type:headers["Content-Type"]=content_type
    if range_header:headers["Range"]=range_header
    req=Request(base+path,data=data,method="POST" if data is not None else "GET",headers=headers)
    with urlopen(req,timeout=90) as response:
        return response.status,dict(response.headers),response.read()

def main():
    p=argparse.ArgumentParser()
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument("--video",help="Local short English/Khmer MP4 with intelligible speech")
    source.add_argument("--url",help="Approved public HTTP(S) MP4/HLS source")
    p.add_argument("--from-lang",choices=["en","km"],default="en")
    p.add_argument("--capture-seconds",type=int,default=30)
    p.add_argument("--timeout",type=int,default=1800)
    p.add_argument("--base",default="http://localhost:8080")
    args=p.parse_args()
    base=args.base.rstrip("/")
    status,_,response=get(base,"/api/models")
    info=json.loads(response)
    if info.get("mode")!="real_subtitles" or not info.get("subtitle_translation_configured"):
        raise RuntimeError("Not ready: enable real_subtitles and install approved offline model assets before running real E2E test")
    target="km" if args.from_lang=="en" else "en"
    if args.url:
        body={"url":args.url,"source_lang":args.from_lang,"target_lang":target,
              "capture_seconds":args.capture_seconds}
        status,_,response=get(base,"/api/jobs/from-url",data=json.dumps(body).encode(),
                              content_type="application/json")
    else:
        video=Path(args.video)
        if not video.is_file() or video.stat().st_size>25_000_000:
            raise RuntimeError("For this test supply a short MP4 smaller than 25 MB")
        boundary="khmerlive-real-e2e-multipart"
        data=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"clip.mp4\"\r\n"
              "Content-Type: video/mp4\r\n\r\n").encode()+video.read_bytes()+f"\r\n--{boundary}--\r\n".encode()
        status,_,response=get(base,"/api/media",data=data,
            content_type="multipart/form-data; boundary="+boundary)
        mid=json.loads(response)["media_id"]
        status,_,response=get(base,"/api/jobs",data=json.dumps(
            {"media_id":mid,"source_lang":args.from_lang,"target_lang":target}).encode(),
            content_type="application/json")
    assert status==202
    jid=json.loads(response)["job_id"]
    print("Submitted real translation job:",jid,flush=True)
    deadline=time.monotonic()+args.timeout
    previous_progress=None
    while time.monotonic()<deadline:
        _,_,body=get(base,"/api/jobs/"+jid)
        job=json.loads(body)
        state=(job["status"],job.get("progress"),job.get("stage"))
        if state!=previous_progress:
            print("  status",state,"partial translation length",len(job.get("translation") or ""),flush=True)
            previous_progress=state
        if job["status"] in ("completed","failed","dispatch_failed","cancelled"):break
        time.sleep(5)
    else:raise TimeoutError("Real model job timed out before completion; check worker CPU/GPU and logs")
    if job["status"]!="completed":
        raise RuntimeError("Real job failed: "+str(job.get("error")))
    if not job.get("has_subtitles") or not job.get("has_output"):
        raise RuntimeError("Job completed but video/subtitles are missing")
    _,_,srt=get(base,"/api/jobs/"+jid+"/subtitles")
    text=srt.decode("utf-8")
    if "-->" not in text or "[DEMO ONLY" in text:
        raise RuntimeError("Subtitle output is missing or a demo placeholder")
    if target=="km" and not re.search("[\u1780-\u17ff]",text):
        raise RuntimeError("Expected Khmer Unicode in generated subtitles")
    if target=="en" and not re.search("[A-Za-z]",text):
        raise RuntimeError("Expected English Latin text in generated subtitles")
    _,_,body=get(base,"/api/jobs/"+jid+"/player-token")
    playback=json.loads(body)
    status,headers,prefix=get(base,playback["video_url"],range_header="bytes=0-4095")
    if status!=206 or b"ftyp" not in prefix[:32]:
        raise RuntimeError("Translated MP4 cannot be previewed with byte ranges")
    print("PASS: real ASR/MT returned target-script subtitles, SRT and playable seekable MP4")
    print("NOTE: This verifies function, NOT translation quality, voice dubbing or perfect accuracy.")
    print("Job:",jid)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
