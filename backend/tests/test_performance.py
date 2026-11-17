"""Performance features: parallel LLM post-editing, thread/device settings,
translation engine selection, stage timing and interrupted-job recovery."""
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import llm_postedit, real_inference
from app.config import Settings
from app.real_inference import TimedText


# ---------- parallel post-editing ----------

def _settings(**kw):
    base = dict(llm_postedit_enabled=True, vllm_postedit_enabled=False, llm_provider="ollama",
                llm_base_url="http://ollama:11434/v1", llm_model="m", llm_timeout_seconds=30,
                llm_max_tokens=128, llm_fail_open=True, llm_total_budget_seconds=900, llm_concurrency=4)
    base.update(kw)
    return SimpleNamespace(**base)


def _client(reply_for, delay=0.05):
    state = {"active": 0, "peak": 0, "calls": 0}
    lock = threading.Lock()

    class Response:
        def __init__(self, content): self.content = content
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": self.content}}]}

    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json, **kw):
            import json as js
            english = js.loads(json["messages"][1]["content"])["english"]
            with lock:
                state["active"] += 1; state["calls"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                time.sleep(delay)
                reply = reply_for(english)
                if isinstance(reply, Exception):
                    raise reply
                return Response(reply)
            finally:
                with lock:
                    state["active"] -= 1
    return Client, state


ROWS = [TimedText(i * 1000, i * 1000 + 900, f"line {i}", "ខ្មែរ") for i in range(8)]


def test_parallel_postedit_runs_concurrently_and_keeps_order(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    Client, state = _client(lambda en: "កែ " + en.split()[1])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    out = llm_postedit.postedit_rows(ROWS, "en", "km")
    assert [r.target_text for r in out] == [f"កែ {i}" for i in range(8)]
    assert [r.start_ms for r in out] == [r.start_ms for r in ROWS]
    assert state["peak"] > 1 and state["peak"] <= 4


def test_parallel_failed_segment_keeps_original(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    Client, _ = _client(lambda en: ValueError("bad") if en == "line 3" else "កែ")
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    out = llm_postedit.postedit_rows(ROWS, "en", "km")
    assert out[3].target_text == "ខ្មែរ" and out[2].target_text == "កែ"


def test_parallel_unreachable_server_stops_early(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_concurrency=2))
    Client, state = _client(lambda en: llm_postedit.httpx.ConnectError("down"))
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    assert llm_postedit.postedit_rows(ROWS, "en", "km") == ROWS
    assert state["calls"] <= 2


def test_parallel_fail_closed_raises(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_fail_open=False))
    Client, _ = _client(lambda en: ValueError("bad"))
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    with pytest.raises(RuntimeError):
        llm_postedit.postedit_rows(ROWS, "en", "km")


def test_unload_llm_sends_keep_alive_zero(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    sent = {}
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json):
            sent.update(url=url, json=json)
            return SimpleNamespace(raise_for_status=lambda: None)
        def get(self, url):
            polls.append(url)
            models = [{"name": "m:latest"}] if len(polls) < 3 else []      # still unloading, then gone
            return SimpleNamespace(json=lambda: {"models": models})
    polls = []
    monkeypatch.setattr(llm_postedit.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    assert llm_postedit.unload_llm() is True
    assert len(polls) == 3 and polls[0] == "http://ollama:11434/api/ps"
    assert sent == {"url": "http://ollama:11434/api/generate", "json": {"model": "m", "keep_alive": 0}}


# ---------- settings ----------

def test_threads_split_cores_between_parallel_jobs(monkeypatch):
    monkeypatch.setattr("os.sched_getaffinity", lambda pid: set(range(12)))
    assert Settings(worker_concurrency=3).threads_per_job() == 4
    assert Settings(worker_concurrency=1).threads_per_job() == 12
    assert Settings(worker_concurrency=20).threads_per_job() == 1
    assert Settings(worker_concurrency=3, cpu_threads=6).threads_per_job() == 6
    assert Settings(asr_cpu_threads=5).threads_per_job() == 5      # legacy name still works


def test_device_per_stage_falls_back_to_inference_device():
    s = Settings(inference_device="cuda", mt_device="cpu")
    assert (s.device_for("asr"), s.device_for("mt"), s.device_for("tts")) == ("cuda", "cpu", "cuda")
    assert Settings().device_for("asr") == "cpu"


def test_asr_compute_type_defaults():
    assert real_inference.asr_compute_type("cuda") == "int8_float16"
    assert real_inference.asr_compute_type("cpu") == "int8"
    assert real_inference.asr_compute_type("cuda", "float16") == "float16"


# ---------- translation engine selection ----------

def test_translator_auto_prefers_ct2_when_converted(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(real_inference, "CTranslate2M2M100", lambda *a: made.append("ct2") or "ct2")
    monkeypatch.setattr(real_inference, "OfflineM2M100", lambda *a: made.append("hf") or "hf")
    real_inference.load_translator.cache_clear()
    ct2 = tmp_path / "ct2"
    assert real_inference.load_translator("/m", "cpu", 2, "auto", str(ct2)) == "hf"      # not converted
    ct2.mkdir(); (ct2 / "model.bin").write_bytes(b"x")
    real_inference.load_translator.cache_clear()
    assert real_inference.load_translator("/m", "cpu", 2, "auto", str(ct2)) == "ct2"
    real_inference.load_translator.cache_clear()
    assert real_inference.load_translator("/m", "cpu", 2, "transformers", str(ct2)) == "hf"
    real_inference.load_translator.cache_clear()


def test_translator_ct2_forced_without_model_errors(tmp_path):
    real_inference.load_translator.cache_clear()
    with pytest.raises(FileNotFoundError):
        real_inference.load_translator("/m", "cpu", 2, "ctranslate2", str(tmp_path / "none"))
    with pytest.raises(ValueError):
        real_inference.load_translator("/m", "cpu", 2, "bogus", "")


# ---------- stage clock ----------

def test_stage_clock_accumulates_repeated_stages(monkeypatch):
    from app import tasks
    t = iter([0, 0, 2, 5, 6, 10, 10])
    monkeypatch.setattr(tasks.time, "monotonic", lambda: next(t))
    c = tasks.StageClock()          # 0
    c.mark("mux")                   # 0
    c.mark("tts")                   # 2  -> mux 2
    c.mark("mux")                   # 5  -> tts 3
    c.mark("upload")                # 6  -> mux +1
    assert c.finish() == {"mux": 3, "tts": 3, "upload": 4, "total": 10}


# ---------- interrupted-job recovery ----------

@pytest.fixture
def db(monkeypatch):
    from app import tasks
    from app.db import Base
    from app.models import MediaAsset, TranslationJob
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "SessionLocal", Session)
    now = datetime.now(timezone.utc)
    with Session() as s:
        s.add(MediaAsset(id="m", filename="v.mp4", object_key="k", content_type="video/mp4", size_bytes=1, sha256="0"))
        for jid, status, age in [("running", "processing", 60), ("dead", "processing", 60),
                                 ("old", "processing", 99999), ("cancel", "cancelling", 60), ("done", "completed", 99999)]:
            s.add(TranslationJob(id=jid, media_id="m", source_lang="en", target_lang="km", status=status,
                                 cancel_requested=False, updated_at=now - timedelta(seconds=age)))
        s.commit()
    return Session, TranslationJob


def test_recovery_fails_jobs_not_running_on_any_worker(db):
    from app import tasks
    Session, Job = db
    assert tasks.recover_interrupted_jobs({"running"}) == 3
    with Session() as s:
        st = {j.id: (j.status, j.stage) for j in s.query(Job)}
    assert st["running"] == ("processing", None)
    assert st["dead"] == ("failed", "interrupted") and st["old"] == ("failed", "interrupted")
    assert st["cancel"][0] == "cancelled" and st["done"][0] == "completed"


def test_recovery_without_worker_list_only_touches_jobs_past_time_limit(db):
    from app import tasks
    Session, Job = db
    assert tasks.recover_interrupted_jobs(None) == 1
    with Session() as s:
        assert s.get(Job, "old").status == "failed" and s.get(Job, "dead").status == "processing"


# ---------- immediate cancel ----------

def test_sigterm_during_job_aborts_and_marks_cancelled(db, monkeypatch):
    import os, signal
    from app import tasks
    Session, Job = db
    with Session() as s:
        j = s.get(Job, "running"); j.status = "queued"; j.cancel_requested = False; s.commit()
    old = signal.signal(signal.SIGTERM, tasks._on_sigterm)
    try:
        def work(job_id):
            with Session() as s:
                j = s.get(Job, job_id); j.status = "cancelling"; j.cancel_requested = True; s.commit()
            os.kill(os.getpid(), signal.SIGTERM)       # what revoke(terminate=True) delivers
            time.sleep(5)
            raise AssertionError("should have been aborted")
        monkeypatch.setattr(tasks, "_translate_media", work)
        t0 = time.monotonic()
        tasks.translate_media.run("running")
        assert time.monotonic() - t0 < 2
    finally:
        signal.signal(signal.SIGTERM, old)
    with Session() as s:
        assert (s.get(Job, "running").status, s.get(Job, "running").stage) == ("cancelled", "cancelled")
    assert tasks._running_job is None


def test_sigterm_without_cancel_request_marks_interrupted(db, monkeypatch):
    from app import tasks
    Session, Job = db
    def work(job_id):
        raise tasks.JobAborted()
    monkeypatch.setattr(tasks, "_translate_media", work)
    tasks.translate_media.run("dead")
    with Session() as s:
        assert s.get(Job, "dead").status == "failed" and s.get(Job, "dead").stage == "interrupted"


def _api_env(monkeypatch, db, active):
    import app.main as main
    from app import tasks
    Session, Job = db

    @contextmanager
    def session():
        with Session() as s:
            yield s
    revoked = []
    control = SimpleNamespace(inspect=lambda timeout: SimpleNamespace(active=lambda: active),
                              revoke=lambda tid, terminate, signal: revoked.append((tid, terminate, signal)))
    monkeypatch.setattr(main, "session", session)
    monkeypatch.setattr(tasks.celery_app, "control", control)
    main.app.dependency_overrides[main.authorize] = lambda: {"admin": True, "user_id": None}
    return main, revoked


def test_cancel_terminates_the_worker_task_running_the_job(db, monkeypatch):
    from fastapi.testclient import TestClient
    main, revoked = _api_env(monkeypatch, db, {"w1": [{"id": "task-9", "args": ["running"]}]})
    try:
        with TestClient(main.app) as http:
            r = http.post("/api/jobs/running/cancel")
    finally:
        main.app.dependency_overrides.clear()
    assert r.json()["status"] == "cancelling"
    assert revoked == [("task-9", True, "SIGTERM")]


def test_cancel_orphaned_job_is_cancelled_immediately(db, monkeypatch):
    from fastapi.testclient import TestClient
    Session, Job = db
    main, revoked = _api_env(monkeypatch, db, None)      # no worker answered
    try:
        with TestClient(main.app) as http:
            r = http.post("/api/jobs/dead/cancel")
    finally:
        main.app.dependency_overrides.clear()
    assert r.json()["status"] == "cancelled" and revoked == []
    with Session() as s:
        assert s.get(Job, "dead").status == "cancelled"


# ---------- LLM preload ----------

def _preload_client(fail_times, calls):
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json):
            calls.append((url, json))
            if len(calls) <= fail_times:
                raise llm_postedit.httpx.ConnectError("starting")
            return SimpleNamespace(raise_for_status=lambda: None)
    return Client


def test_preload_loads_model_without_generating(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    calls = []
    monkeypatch.setattr(llm_postedit.httpx, "Client", _preload_client(0, calls))
    assert llm_postedit.preload_llm() is True
    assert calls == [("http://ollama:11434/api/generate", {"model": "m"})]   # no prompt -> load only


def test_preload_retries_while_ollama_starts(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    monkeypatch.setattr(llm_postedit.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(llm_postedit.httpx, "Client", _preload_client(2, calls))
    assert llm_postedit.preload_llm() is True and len(calls) == 3


def test_preload_gives_up_quietly(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    monkeypatch.setattr(llm_postedit.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(llm_postedit.httpx, "Client", _preload_client(99, calls))
    assert llm_postedit.preload_llm(attempts=3) is False and len(calls) == 3


def test_preload_skipped_when_llm_disabled(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_postedit_enabled=False))
    assert llm_postedit.preload_llm() is False


def test_stored_youtube_copy_is_reused_not_redownloaded(monkeypatch, tmp_path):
    """Second run of a YouTube video replays the stored copy (no yt-dlp call)."""
    import inspect
    from app import tasks
    src = inspect.getsource(tasks._translate_media)
    i = src.index('reused=False'); j = src.index('elif media.source_kind=="youtube"')
    block = src[i:j]
    assert 'media.sha256 not in (None,"","pending")' in block and "s3.download_file" in block
