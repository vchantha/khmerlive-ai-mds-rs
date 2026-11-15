from app.config import settings
from app.main import models


def test_upload_limits_report_effective_server_settings(monkeypatch):
    monkeypatch.setattr(settings,"model_mode","demo")
    monkeypatch.setattr(settings,"max_video_duration_seconds",7200)
    monkeypatch.setattr(settings,"max_upload_mb",512)
    result=models()
    assert result["max_video_duration_seconds"]==7200
    assert result["max_upload_mb"]==512
    assert result["speech_dubbing_available"] is False
