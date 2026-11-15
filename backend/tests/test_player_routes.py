"""FastAPI HTTP preview and WebVTT routes tested with a fake S3 client.

These route tests do not require PostgreSQL/MinIO, but they exercise the same
HTTP 206 / Content-Range behavior used by browsers in the actual Docker stack.
"""
from fastapi.testclient import TestClient
from app.main import app
import app.main as main

class FakeBody:
    def __init__(self,data:bytes):self.data=data;self.closed=False
    def iter_chunks(self,chunk_size:int=262144):
        yield self.data
    def read(self,n:int=-1):
        return self.data if n<0 else self.data[:n]
    def close(self):self.closed=True

class FakeS3:
    def __init__(self):
        self.media=b"0000ftyp"+"a".encode()*100
        self.sub=b"1\n00:00:00,000 --> 00:00:01,500\n\xe1\x9e\x9f\xe1\x9e\xbd\xe1\x9e\x9f\xe1\x9f\x92\xe1\x9e\x8f\xe1\x9e\xb8\n"
    def head_object(self,**kw):
        return {"ContentLength":len(self.media)}
    def get_object(self,**kw):
        data=self.sub if kw["Key"]=="sample.srt" else self.media
        if kw.get("Range"):
            start,end=map(int,kw["Range"].split("=")[1].split("-"))
            data=data[start:end+1]
        return {"Body":FakeBody(data)}

def test_preview_supports_http_ranges(monkeypatch):
    monkeypatch.setattr(main,"playback_job",lambda job,token:("sample.mp4","sample.srt"))
    monkeypatch.setattr(main,"client",lambda:FakeS3())
    with TestClient(app) as http:
        r=http.get("/api/jobs/uuid/preview",params={"token":"a"*30},headers={"Range":"bytes=0-9"})
    assert r.status_code==206
    assert r.headers["accept-ranges"]=="bytes"
    assert r.headers["content-range"]=="bytes 0-9/108"
    assert len(r.content)==10

def test_preview_invalid_ranges_return_416(monkeypatch):
    monkeypatch.setattr(main,"playback_job",lambda job,token:("sample.mp4",None))
    monkeypatch.setattr(main,"client",lambda:FakeS3())
    with TestClient(app) as http:
        r=http.get("/api/jobs/uuid/preview",params={"token":"a"*30},headers={"Range":"bytes=999-2000"})
    assert r.status_code==416

def test_webvtt_route_converts_khmer_srt(monkeypatch):
    monkeypatch.setattr(main,"playback_job",lambda job,token:("sample.mp4","sample.srt"))
    monkeypatch.setattr(main,"client",lambda:FakeS3())
    with TestClient(app) as http:
        r=http.get("/api/jobs/uuid/captions.vtt",params={"token":"a"*30})
    assert r.status_code==200
    assert r.text.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.500" in r.text
