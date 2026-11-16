"""YouTube video ingestion via yt-dlp.

A YouTube link is a web page, not a media file, so it cannot be read by FFmpeg
like an allowlisted MP4/HLS URL. Only a canonical single-video URL built from a
validated 11-character video ID is ever passed to yt-dlp: playlists, channels,
arbitrary query parameters and other hosts are rejected up front.

Downloading YouTube content may be restricted by YouTube's Terms of Service and
by copyright. Operators are responsible for only processing videos they have
the rights to use.
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                 "youtu.be", "www.youtube-nocookie.com", "youtube-nocookie.com"}
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PATH_ID = re.compile(r"^/(?:shorts|live|embed|v)/([A-Za-z0-9_-]{11})(?:[/?].*)?$")

class YouTubeURLRejected(ValueError):
    pass

def is_youtube_host(url: str) -> bool:
    try:
        host = (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host in YOUTUBE_HOSTS

def youtube_video_id(url: str) -> str:
    """Return the video ID of a single YouTube video URL, or raise."""
    if not isinstance(url, str) or len(url) > 2048:
        raise YouTubeURLRejected("YouTube URL is invalid or too long")
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or host not in YOUTUBE_HOSTS:
        raise YouTubeURLRejected("Not a YouTube URL")
    if parts.username or parts.password or parts.port not in (None, 80, 443):
        raise YouTubeURLRejected("Credentials or custom ports are not allowed in YouTube URLs")
    candidate = None
    if host == "youtu.be":
        candidate = parts.path.lstrip("/").split("/")[0]
    elif parts.path == "/watch":
        candidate = (parse_qs(parts.query).get("v") or [""])[0]
    else:
        match = _PATH_ID.match(parts.path)
        candidate = match.group(1) if match else None
    if not candidate or not _VIDEO_ID.match(candidate):
        raise YouTubeURLRejected("Use a link to a single YouTube video (watch, youtu.be, shorts or live URL)")
    return candidate

def canonical_url(video_id: str) -> str:
    if not _VIDEO_ID.match(video_id):
        raise YouTubeURLRejected("Invalid YouTube video ID")
    return "https://www.youtube.com/watch?v=" + video_id

def download_command(video_id: str, destination: Path, max_seconds: int, max_bytes: int) -> list[str]:
    # Keep a small margin: stream-copy cuts can overshoot the end by a fraction of a second.
    section_end = max(1, int(max_seconds) - 3)
    return ["python", "-m", "yt_dlp",
            "--no-playlist", "--no-progress", "--no-warnings",
            "--no-cache-dir", "--no-mtime", "--restrict-filenames",
            "--socket-timeout", "30", "--retries", "3",
            # Never record a live broadcast.
            "--match-filter", "!is_live", "--break-match-filters", "!is_live",
            # Long videos: download only the first section the worker may process.
            "--download-sections", f"*0-{section_end}",
            "--max-filesize", str(int(max_bytes)),
            # Prefer browser-friendly H.264 + AAC up to 720p; fall back to best MP4.
            "-f", "bv*[vcodec^=avc1][height<=720]+ba[acodec^=mp4a]/b[ext=mp4][height<=720]/bv*[height<=720]+ba/b",
            "--merge-output-format", "mp4",
            "-o", str(destination),
            # Report the original duration so callers know whether it was trimmed.
            "--no-simulate", "--quiet", "--print", "before_dl:duration=%(duration)s",
            "--", canonical_url(video_id)]

def download_youtube(video_id: str, destination: Path, max_seconds: int, max_bytes: int,
                     timeout: int = 1800) -> float | None:
    """Download a video (first ``max_seconds`` only). Returns the original duration."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(download_command(video_id, destination, max_seconds, max_bytes),
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 or not destination.exists():
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "no output"
        if "does not pass filter" in message or proc.returncode == 101:
            message = "Live broadcasts are not supported"
        raise RuntimeError("YouTube download failed: " + message[:400])
    for line in proc.stdout.splitlines():
        if line.startswith("duration="):
            try:
                return float(line.split("=", 1)[1])
            except ValueError:
                return None
    return None
