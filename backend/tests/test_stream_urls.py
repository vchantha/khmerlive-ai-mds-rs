import socket
import pytest
from app.stream_urls import validate_stream_url, capture_seconds_valid, StreamURLRejected

def test_default_requires_explicit_allowlist(monkeypatch):
    monkeypatch.delenv("STREAM_ALLOWED_HOSTS", raising=False)
    with pytest.raises(StreamURLRejected, match="disabled"):
        validate_stream_url("https://media.example.com/live/index.m3u8")

def test_private_or_local_addresses_rejected(monkeypatch):
    monkeypatch.setenv("STREAM_ALLOWED_HOSTS", "media.example.com")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
    ])
    with pytest.raises(StreamURLRejected, match="restricted"):
        validate_stream_url("https://media.example.com/live/index.m3u8")

def test_public_allowlisted_https_url_passes(monkeypatch):
    monkeypatch.setenv("STREAM_ALLOWED_HOSTS", "media.example.com")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))
    ])
    assert validate_stream_url("https://media.example.com/live/index.m3u8").endswith(".m3u8")

@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "rtsp://media.example.com/live", "https://127.0.0.1/a",
    "https://admin:password@media.example.com/test", "https://media.example.com:9999/stream"
])
def test_unsupported_sources_rejected(monkeypatch, url):
    monkeypatch.setenv("STREAM_ALLOWED_HOSTS", "media.example.com")
    with pytest.raises(StreamURLRejected):
        validate_stream_url(url)

@pytest.mark.parametrize("n", [5, 15, 30, 60, 120])
def test_allowed_duration(n):
    assert capture_seconds_valid(n) == n

@pytest.mark.parametrize("n", [0, 3, 121, -1])
def test_disallowed_duration(n):
    with pytest.raises(StreamURLRejected):
        capture_seconds_valid(n)
