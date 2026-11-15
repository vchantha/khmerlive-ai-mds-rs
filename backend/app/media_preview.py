"""Short-lived playback grants, HTTP byte ranges and WebVTT conversion.

The signed preview token is a *temporary bearer grant*, not a user credential.
Only the authenticated, owner-scoped job endpoint may mint one.
"""
import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass

class InvalidPlaybackToken(ValueError): pass
class InvalidByteRange(ValueError): pass

def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def issue_playback_token(job_id: str, owner_id: str | None, secret: str, ttl_seconds: int = 180, *, now: int | None = None) -> str:
    if not 10 <= ttl_seconds <= 600:
        raise ValueError("Playback token lifetime must be 10–600 seconds")
    payload = {"job":job_id,"owner":owner_id,"exp":int(time.time() if now is None else now)+ttl_seconds,"v":1}
    body = b64(json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8"))
    signature = b64(hmac.new(secret.encode(),body.encode(),hashlib.sha256).digest())
    return body+"."+signature

def check_playback_token(token: str, job_id: str, owner_id: str | None, secret: str, *, now: int | None = None) -> None:
    try:
        if len(token)>2048:
            raise InvalidPlaybackToken("Invalid playback token")
        body, signature = token.split(".")
        expected = b64(hmac.new(secret.encode(),body.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(signature,expected):
            raise InvalidPlaybackToken("Invalid playback signature")
        payload = json.loads(base64.urlsafe_b64decode(body+"="*((-len(body))%4)))
        if payload.get("v")!=1 or payload.get("job")!=job_id or payload.get("owner")!=owner_id:
            raise InvalidPlaybackToken("Playback scope mismatch")
        if int(payload["exp"])<=int(time.time() if now is None else now):
            raise InvalidPlaybackToken("Playback token expired")
    except (UnicodeError,ValueError,KeyError,TypeError,base64.binascii.Error) as exc:
        if isinstance(exc,InvalidPlaybackToken):raise
        raise InvalidPlaybackToken("Invalid playback token") from exc

@dataclass(frozen=True)
class ByteRange:
    start:int
    end:int
    total:int
    @property
    def length(self)->int:return self.end-self.start+1
    @property
    def content_range(self)->str:return f"bytes {self.start}-{self.end}/{self.total}"
    @property
    def s3_range(self)->str:return f"bytes={self.start}-{self.end}"

_RANGE_RE=re.compile(r"^bytes=(\d*)-(\d*)$")

def parse_byte_range(value: str | None, size: int) -> ByteRange | None:
    if size<0:raise ValueError("Invalid object size")
    if value is None:return None
    m=_RANGE_RE.fullmatch(value.strip())
    if not m or (not m.group(1) and not m.group(2)) or size==0:
        raise InvalidByteRange("Invalid or unsatisfiable Range")
    a,b=m.groups()
    if a:
        start=int(a)
        if start>=size:raise InvalidByteRange("Requested range beyond object")
        end=min(size-1,int(b)) if b else size-1
        if start>end:raise InvalidByteRange("Invalid byte range bounds")
    else:
        count=int(b)
        if count<=0:raise InvalidByteRange("Suffix range must be positive")
        start=max(0,size-count)
        end=size-1
    return ByteRange(start,end,size)

_TIMESTAMP=re.compile(r"(\d{2}:\d{2}:\d{2}),(\d{3})")

def srt_to_webvtt(srt: str)->str:
    content=srt.lstrip("\ufeff").replace("\r\n","\n").replace("\r","\n").strip()
    if not content or "-->" not in content:
        raise ValueError("Subtitle file has no valid cues")
    return "WEBVTT\n\n"+_TIMESTAMP.sub(r"\1.\2",content)+"\n"
