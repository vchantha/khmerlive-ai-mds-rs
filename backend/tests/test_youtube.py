from pathlib import Path
import pytest
from app.youtube import (is_youtube_host, youtube_video_id, canonical_url,
                         download_command, YouTubeURLRejected)

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&t=42s",
    "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/live/dQw4w9WgXcQ?feature=share",
    "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    " https://music.youtube.com/watch?v=dQw4w9WgXcQ ",
])
def test_single_video_urls_resolve_to_id(url):
    assert is_youtube_host(url)
    assert youtube_video_id(url) == "dQw4w9WgXcQ"

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/playlist?list=PL123",
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ%27;rm",
    "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
    "https://user:pw@youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com:8443/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
])
def test_rejects_non_single_video_or_unsafe_urls(url):
    with pytest.raises(YouTubeURLRejected):
        youtube_video_id(url)

def test_other_hosts_are_not_youtube():
    assert not is_youtube_host("https://cdn.example.org/video.mp4")
    assert not is_youtube_host("https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ")

def test_download_uses_only_canonical_url_and_limits():
    cmd = download_command("dQw4w9WgXcQ", Path("/tmp/x.mp4"), 600, 1024)
    assert cmd[-1] == canonical_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert cmd[-2] == "--"
    assert "--no-playlist" in cmd
    assert "!is_live" in cmd
    assert cmd[cmd.index("--download-sections") + 1] == "*0-597"
    assert cmd[cmd.index("--max-filesize") + 1] == "1024"

def test_parse_printed_metadata():
    from app.youtube import parse_printed
    info = parse_printed("duration=2053\ntitle=Speak = English\nheight=NA\nis_live=False\njunk\nother=1\n")
    assert info == {"duration": 2053.0, "title": "Speak = English", "is_live": False}

def test_safe_title_strips_path_and_control_chars():
    from app.youtube import safe_title
    assert safe_title("a/b\\c\x00d", "x") == "a b c d"
    assert safe_title("", "YouTube abc") == "YouTube abc"
