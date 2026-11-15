#!/usr/bin/env python3
"""End-to-end demo test over HTTP: upload -> PostgreSQL -> Celery -> video preview.

Runs against a launched Docker Compose stack. This does NOT test real AI quality.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from urllib.parse import urlencode

BASE=os.getenv("KHMERLIVE_BASE_URL","http://localhost:8080").rstrip("/")
def api_key():
    val=os.environ.get("API_KEY","")
    if val:return val
    file=Path(".env")
    if file.exists():
        for line in file.read_text().splitlines():
            if line.startswith("API_KEY="):
                return line.split("=",1)[1].strip().strip('"')
    raise RuntimeError("Provide API_KEY via environment or a local .env")

def request(path:str,*,method:str="GET",data:bytes|None=None,content_type:str|None=None,range_header:str|None=None):
    headers={"X-API-Key":api_key()}
    if content_type:headers["Content-Type"]=content_type
    if range_header:headers["Range"]=range_header
    req=Request(BASE+path,data=data,method=method,headers=headers)
    with urlopen(req,timeout=30) as resp:
        return resp.status,dict(resp.headers),resp.read()

def main():
    code,_,body=request("/api/models")
    mode=json.loads(body)["mode"]
    if mode!="demo":
        raise RuntimeError("This test is for DEMO mode; use the real-model evaluation on actual weights")
    with tempfile.TemporaryDirectory() as td:
        media=Path(td)/"sample.mp4"
        subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
            "-f","lavfi","-i","color=c=blue:s=320x180:r=25",
            "-f","lavfi","-i","sine=frequency=440:sample_rate=44100",
            "-t","2","-c:v","libx264","-pix_fmt","yuv420p",
            "-c:a","aac",str(media)],check=True,timeout=30)
        boundary="khmerlive-integration-test-boundary"
        data=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sample.mp4\"\r\n"
              "Content-Type: video/mp4\r\n\r\n").encode()+media.read_bytes()+f"\r\n--{boundary}--\r\n".encode()
        status,_,body=request("/api/media",method="POST",data=data,
            content_type="multipart/form-data; boundary="+boundary)
        assert status==201
        media_id=json.loads(body)["media_id"]
        payload=json.dumps({"media_id":media_id,"source_lang":"en","target_lang":"km"}).encode()
        status,_,body=request("/api/jobs",method="POST",data=payload,content_type="application/json")
        assert status==202
        job_id=json.loads(body)["job_id"]
        for _ in range(80):
            status,_,body=request("/api/jobs/"+job_id)
            job=json.loads(body)
            if job["status"] in ("completed","failed","dispatch_failed"):break
            time.sleep(2)
        else:raise TimeoutError("Worker did not finish within 160 seconds")
        if job["status"]!="completed":
            raise RuntimeError("Demo worker did not complete: "+str(job.get("error")))
        assert job["has_output"]
        assert not job["has_subtitles"],"Demo should not claim to have translated subtitles"
        assert "DEMO ONLY" in (job.get("translation") or "")
        status,_,body=request("/api/jobs/"+job_id+"/player-token")
        assert status==200
        token=json.loads(body)["token"]
        path="/api/jobs/"+job_id+"/preview?"+urlencode({"token":token})
        status,headers,video=request(path,range_header="bytes=0-4095")
        assert status==206,(status,headers)
        assert headers.get("Content-Range","").startswith("bytes 0-")
        assert b"ftyp" in video[:32]
        print("PASS: HTTP upload -> queue -> PostgreSQL -> Celery -> H.264 output -> authenticated player byte range")
        print("Job:",job_id)
        print("NOTE: DEMO placeholder is not translated speech.")
if __name__=="__main__":main()
