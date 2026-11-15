"""FFmpeg media smoke test; does not pretend to test ASR/MT model accuracy."""
import shutil
import subprocess
from pathlib import Path
import pytest

@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="FFmpeg/FFprobe not installed")
def test_mux_srt_as_selectable_mp4_subtitle(tmp_path:Path):
    source=tmp_path/"input.mp4"
    srt=tmp_path/"translated.srt"
    output=tmp_path/"output.mp4"
    subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
        "-f","lavfi","-i","color=c=black:s=320x180:r=25",
        "-f","lavfi","-i","sine=frequency=440:sample_rate=44100",
        "-t","2","-c:v","mpeg4","-c:a","aac",str(source)],
        check=True,timeout=30)
    srt.write_text("1\n00:00:00,000 --> 00:00:01,750\nសួស្តី!\n",encoding="utf-8")
    subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
        "-i",str(source),"-i",str(srt),
        "-map","0:v:0","-map","0:a:0?","-map","1:0",
        "-c:v","copy","-c:a","copy","-c:s","mov_text",
        "-metadata:s:s:0","language=khm",
        "-disposition:s:0","default","-movflags","+faststart",str(output)],
        check=True,timeout=30)
    codec=subprocess.check_output(["ffprobe","-v","error",
        "-select_streams","s","-show_entries","stream=codec_name",
        "-of","default=noprint_wrappers=1:nokey=1",str(output)],text=True)
    assert "mov_text" in codec
    assert output.stat().st_size>1024

@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="FFmpeg/FFprobe not installed")
def test_output_codec_args_copies_compatible_and_transcodes_others(tmp_path:Path):
    from app.tasks import output_codec_args
    ok=tmp_path/"h264.mp4"
    bad=tmp_path/"mpeg4.mp4"
    for path,vcodec in ((ok,"libx264"),(bad,"mpeg4")):
        subprocess.run(["ffmpeg","-v","error","-nostdin","-y",
            "-f","lavfi","-i","color=c=black:s=320x180:r=25",
            "-f","lavfi","-i","sine=frequency=440:sample_rate=44100",
            "-t","1","-c:v",vcodec,"-pix_fmt","yuv420p","-c:a","aac",str(path)],
            check=True,timeout=30)
    assert output_codec_args(ok)==["-c:v","copy","-c:a","copy"]
    args=output_codec_args(bad)
    assert args[:2]==["-c:v","libx264"] and args[-2:]==["-c:a","copy"]
