"""Test the real FFmpeg segmented-recording path against a local HTTP MP4.

This tests media transport and concatenation; it does not benchmark AI models.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import shutil
import subprocess
import pytest

from app.live_capture import segment_command,capture_chunks,combine_chunks,duration_ms

@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),reason="FFmpeg unavailable")
def test_segment_recording_and_concat_from_http(tmp_path:Path):
    source=tmp_path/"input.mp4"
    subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
        "-f","lavfi","-i","color=c=black:s=320x180:r=25",
        "-f","lavfi","-i","sine=frequency=440:sample_rate=44100",
        "-t","5","-c:v","libx264","-preset","ultrafast","-c:a","aac",str(source)],
        check=True,timeout=30)
    handler=partial(SimpleHTTPRequestHandler,directory=str(tmp_path))
    server=ThreadingHTTPServer(("127.0.0.1",0),handler)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        url=f"http://127.0.0.1:{server.server_port}/input.mp4"
        command=segment_command(url,5,tmp_path/"chunks",2)
        assert "-f" in command and "segment" in command
        segments=list(capture_chunks(url,5,tmp_path/"chunks",lambda:None,2))
        assert segments
        assert all(p.exists() and duration_ms(p)>0 for p,_ in segments)
        output=tmp_path/"joined.mp4"
        combine_chunks(tmp_path/"chunks",output)
        codecs=subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0",
            "-show_entries","stream=codec_name","-of","default=nk=1:nw=1",str(output)],text=True)
        assert "h264" in codecs
        assert output.stat().st_size>1024
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),reason="FFmpeg unavailable")
def test_hls_manifest_segments_are_accepted(tmp_path:Path):
    playlist=tmp_path/"index.m3u8"
    subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
        "-f","lavfi","-i","color=c=black:s=320x180:r=25",
        "-f","lavfi","-i","sine=frequency=650:sample_rate=44100",
        "-t","6","-c:v","libx264","-g","50","-keyint_min","50",
        "-sc_threshold","0","-preset","ultrafast","-c:a","aac",
        "-f","hls","-hls_time","2","-hls_list_size","0",
        "-hls_segment_filename",str(tmp_path/"part_%03d.ts"),str(playlist)],
        check=True,timeout=30)
    handler=partial(SimpleHTTPRequestHandler,directory=str(tmp_path))
    server=ThreadingHTTPServer(("127.0.0.1",0),handler)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        url=f"http://127.0.0.1:{server.server_port}/index.m3u8"
        parts=list(capture_chunks(url,5,tmp_path/"hls-segments",lambda:None,2))
        assert len(parts)>=2
        out=tmp_path/"hls-result.mp4"
        combine_chunks(tmp_path/"hls-segments",out)
        assert out.stat().st_size>2048
    finally:
        server.shutdown()
        server.server_close()
