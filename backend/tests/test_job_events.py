"""Pipeline log: step events, LLM task records, events API and purge cleanup."""
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app import joblog, llm_postedit
from app.db import Base
from app.models import JobEvent, MediaAsset, TranslationJob
from app.real_inference import TimedText


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def session():
        with Session() as s:
            yield s
    monkeypatch.setattr(main, "session", session)
    monkeypatch.setattr(joblog, "SessionLocal", Session)
    monkeypatch.setattr(main, "client", lambda: SimpleNamespace(delete_objects=lambda **k: None))
    actor = {"admin": True, "user_id": None}
    main.app.dependency_overrides[main.authorize] = lambda: actor
    with Session() as s:
        s.add(MediaAsset(id="m", filename="v.mp4", object_key="k", content_type="video/mp4", size_bytes=1, sha256="0", owner_user_id=None))
        s.add(TranslationJob(id="j", media_id="m", source_lang="en", target_lang="km", status="completed", cancel_requested=False))
        s.commit()
    with TestClient(main.app) as http:
        yield http, Session, actor
    main.app.dependency_overrides.clear()


def test_log_event_stores_details_and_clips_long_text(env):
    http, Session, _ = env
    joblog.log_event("j", "asr_translate", "Finished", seconds=12.345, segments=40, text="x" * 5000)
    with Session() as s:
        e = s.scalars(select(JobEvent)).one()
    assert (e.stage, e.seconds) == ("asr_translate", 12.345)
    import json
    d = json.loads(e.data)
    assert d["segments"] == 40 and len(d["text"]) < 2100


def test_log_event_never_raises(monkeypatch):
    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(joblog, "SessionLocal", broken)
    joblog.log_event("j", "x", "still fine")


def test_events_api_lists_steps_and_filters_llm(env):
    http, _, _ = env
    joblog.log_event("j", "job", "Job started")
    joblog.log_llm_tasks("j", [{"index": 0, "english": "hi", "draft": "ក", "output": "សួស្តី", "status": "edited", "seconds": 1.2},
                               {"index": 1, "english": "x", "draft": "ខ", "output": None, "status": "kept original (rejected output)", "seconds": 0.8}])
    items = http.get("/api/jobs/j/events").json()["items"]
    assert [i["stage"] for i in items] == ["job", "llm", "llm"]
    llm = http.get("/api/jobs/j/events", params={"stage": "llm"}).json()["items"]
    assert llm[0]["data"]["output"] == "សួស្តី" and llm[1]["level"] == "warning"


def test_events_api_respects_ownership(env):
    http, _, actor = env
    actor.update(admin=False, user_id="someone")
    assert http.get("/api/jobs/j/events").status_code == 404


def test_trash_and_restore_are_logged_and_purge_removes_events(env):
    http, Session, _ = env
    http.delete("/api/jobs/j")
    http.post("/api/trash/job/j/restore")
    msgs = [i["message"] for i in http.get("/api/jobs/j/events").json()["items"]]
    assert msgs == ["Moved to Trash", "Restored from Trash"]
    http.delete("/api/jobs/j"); http.delete("/api/trash/job/j")
    with Session() as s:
        assert s.scalars(select(JobEvent)).all() == []


def test_postedit_report_records_each_line(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", SimpleNamespace(
        llm_postedit_enabled=True, vllm_postedit_enabled=False, llm_provider="ollama",
        llm_base_url="http://ollama:11434/v1", llm_model="m", llm_timeout_seconds=30, llm_max_tokens=128,
        llm_fail_open=True, llm_total_budget_seconds=900, llm_concurrency=1))
    replies = iter(["កែ", "no khmer here"])

    class Client:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json, **k):
            c = next(replies)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": c}}]})
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [TimedText(0, 1000, "one", "មួយ"), TimedText(1000, 2000, "two", "ពីរ")]
    report = []
    llm_postedit.postedit_rows(rows, "en", "km", report=report)
    assert [(t["index"], t["status"]) for t in report] == [(0, "edited"), (1, "kept original (rejected output)")]
    assert report[0]["english"] == "one" and report[0]["draft"] == "មួយ" and report[0]["output"] == "កែ"
    assert report[1]["error"] and report[0]["seconds"] is not None


def test_stage_clock_logs_finished_with_notes(monkeypatch):
    from app import tasks
    events = []
    monkeypatch.setattr(tasks, "log_event", lambda job, stage, msg, **kw: events.append((stage, msg, kw)))
    c = tasks.StageClock("j")
    c.mark("tts"); c.note(lines=3); c.mark(None)
    assert events[0][1] == "Started: Khmer voice synthesis"
    assert events[1][1] == "Finished: Khmer voice synthesis" and events[1][2]["lines"] == 3 and "seconds" in events[1][2]
