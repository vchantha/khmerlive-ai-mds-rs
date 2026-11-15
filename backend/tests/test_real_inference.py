from pathlib import Path
import pytest
from app.real_inference import TimedText, build_srt, timestamp, model_paths

def test_timestamp_hours_and_milliseconds():
    assert timestamp(3_661_005) == "01:01:01,005"
    assert timestamp(-50) == "00:00:00,000"

def test_khmer_subtitle_utf8_and_segment_timing():
    result=build_srt([TimedText(0, 1200, "Hello", "សួស្តី"),
                      TimedText(1500, 2300, "Welcome", "សូមស្វាគមន៍")])
    assert "00:00:00,000 --> 00:00:01,200" in result
    assert "សួស្តី" in result
    assert "សូមស្វាគមន៍" in result
    assert result.count("-->") == 2

def test_subtitle_empty_text_skipped():
    assert build_srt([TimedText(0,100,"hello","")]) == ""

def test_model_requirements_fail_safely(tmp_path):
    with pytest.raises(FileNotFoundError, match="Offline model asset missing"):
        model_paths(str(tmp_path/"asr"),str(tmp_path/"mt"))
