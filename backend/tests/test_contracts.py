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
    assert {"/api/media","/api/jobs","/api/jobs/{job_id}","/api/health/live"}.issubset(paths)
