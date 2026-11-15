"""Restricted public HTTP(S) media source ingestion.

This is an MVP-level host allowlist, not an SSRF sandbox. Configure network
egress policy in production. Never expose the stream URL or credentials via API.
"""
import ipaddress
import os
import socket
from urllib.parse import urlsplit

class StreamURLRejected(ValueError):
    pass

def validate_stream_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise StreamURLRejected("Stream URL is invalid or too long")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise StreamURLRejected("Only HTTP(S) stream URLs are supported")
    if parts.username or parts.password or parts.fragment:
        raise StreamURLRejected("Credentials or fragments in URLs are not allowed")
    if parts.port not in (None, 80, 443):
        raise StreamURLRejected("Non-standard ports are not allowed")
    host = parts.hostname.lower().rstrip(".")
    allowed = {x.strip().lower().rstrip(".") for x in os.getenv("STREAM_ALLOWED_HOSTS", "").split(",") if x.strip()}
    if not allowed:
        raise StreamURLRejected("URL ingestion is disabled until STREAM_ALLOWED_HOSTS is configured")
    if host not in allowed:
        raise StreamURLRejected("Host is not in the configured stream allowlist")
    try:
        addresses = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as ex:
        raise StreamURLRejected("Stream host could not be resolved") from ex
    if not addresses:
        raise StreamURLRejected("Stream host did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise StreamURLRejected("Stream URL resolves to a restricted IP address")
    return url

def capture_seconds_valid(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool) or not (5 <= n <= 120):
        raise StreamURLRejected("Capture duration must be 5–120 seconds")
    return n
