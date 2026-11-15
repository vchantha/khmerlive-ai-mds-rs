from pathlib import Path
from app.adapters import DemoASR, DemoMT
from app.main import app,JobCreate

def test_demo_never_claims_translation():
    assert "DEMO ONLY" in DemoASR().transcribe(Path("unused.wav"),"km").text
    assert "no" in DemoMT().translate("hello","en","km")

def test_languages():
    assert JobCreate(media_id="x",source_lang="en",target_lang="km")

def test_routes_exist():
    paths={r.path for r in app.routes}
    assert {"/api/media","/api/jobs","/api/jobs/{job_id}","/api/health/live","/api/dashboard","/api/system"}.issubset(paths)

def test_job_serialization_contains_real_progress():
    from datetime import datetime,timezone
    from app.main import format_job
    from app.models import MediaAsset,TranslationJob
    media=MediaAsset(id="m",filename="sample.mp4",object_key="uploads/test",content_type="video/mp4",size_bytes=2048,sha256="x"*64)
    job=TranslationJob(id="j",media_id="m",source_lang="en",target_lang="km",status="processing",progress=45,stage="demo transcription",created_at=datetime.now(timezone.utc))
    data=format_job(job,media)
    assert data["filename"]=="sample.mp4"
    assert data["progress"]==45
    assert data["stage"]=="demo transcription"
    assert data["has_output"] is False
