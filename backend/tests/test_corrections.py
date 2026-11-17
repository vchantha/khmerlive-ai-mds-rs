"""Translation review: segments, corrections API, dataset export, training split."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app import joblog
from app.db import Base
from app.models import MediaAsset, TranslationCorrection, TranslationJob

SEGS = [{"start_ms": 0, "end_ms": 2000, "source": "Here we are in front of the elephants.",
         "machine": "អ៊ីនធឺណិត", "llm": "នៅមុខអ៊ីនធឺណិត", "final": "នៅមុខអ៊ីនធឺណិត"},
        {"start_ms": 2000, "end_ms": 4000, "source": "And that's cool.", "machine": "នេះល្អ", "llm": None, "final": "នេះល្អ"}]


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
    actor = {"admin": False, "user_id": "u1"}
    main.app.dependency_overrides[main.authorize] = lambda: actor
    with Session() as s:
        s.add(MediaAsset(id="m", filename="zoo.mp4", object_key="k", content_type="video/mp4", size_bytes=1, sha256="0", owner_user_id="u1"))
        s.add(TranslationJob(id="j", media_id="m", source_lang="en", target_lang="km", status="completed",
                             cancel_requested=False, owner_user_id="u1", segments=json.dumps(SEGS, ensure_ascii=False)))
        s.add(TranslationJob(id="old", media_id="m", source_lang="en", target_lang="km", status="completed",
                             cancel_requested=False, owner_user_id="u1"))
        s.commit()
    with TestClient(main.app) as http:
        yield http, Session, actor
    main.app.dependency_overrides.clear()


def put(http, items, job="j"):
    return http.put(f"/api/jobs/{job}/corrections", json={"items": items})


def test_segments_list_english_machine_llm_and_final(env):
    http, *_ = env
    r = http.get("/api/jobs/j/segments").json()
    assert r["available"] and r["verified"] == 0
    assert r["items"][0]["source"].startswith("Here we are") and r["items"][0]["machine"] == "អ៊ីនធឺណិត"
    assert r["items"][0]["corrected"] is None


def test_save_correction_and_approval(env):
    http, Session, _ = env
    r = put(http, [{"index": 0, "corrected_text": "យើងនៅមុខដំរី។"}, {"index": 1, "corrected_text": "នេះល្អ"}])
    assert r.status_code == 200 and r.json() == {"saved": 2, "removed": 0, "verified": 2}
    items = http.get("/api/jobs/j/segments").json()["items"]
    assert items[0]["corrected"] == "យើងនៅមុខដំរី។" and not items[0]["approved_unchanged"]
    assert items[1]["approved_unchanged"]                      # same as final -> confirmed correct
    with Session() as s:
        c = s.scalars(select(TranslationCorrection).where(TranslationCorrection.segment_index == 0)).one()
        assert c.source_text.startswith("Here we are") and c.machine_text == "អ៊ីនធឺណិត" and c.created_by == "u1"


def test_update_and_clear_correction(env):
    http, *_ = env
    put(http, [{"index": 0, "corrected_text": "ក"}])
    put(http, [{"index": 0, "corrected_text": "យើងនៅមុខដំរី។"}])
    assert http.get("/api/jobs/j/segments").json()["items"][0]["corrected"] == "យើងនៅមុខដំរី។"
    r = put(http, [{"index": 0, "corrected_text": ""}])
    assert r.json()["removed"] == 1 and r.json()["verified"] == 0


def test_validation(env):
    http, *_ = env
    assert put(http, [{"index": 0, "corrected_text": "no khmer here"}]).status_code == 422
    assert put(http, [{"index": 9, "corrected_text": "ក"}]).status_code == 422
    assert put(http, [{"index": 0, "corrected_text": "ក"}], job="old").status_code == 409     # no stored lines
    assert http.get("/api/jobs/old/segments").json()["available"] is False


def test_other_users_cannot_review(env):
    http, _, actor = env
    actor.update(user_id="u2")
    assert http.get("/api/jobs/j/segments").status_code == 404
    assert put(http, [{"index": 0, "corrected_text": "ក"}]).status_code == 404


def test_dataset_summary_and_jsonl_export(env):
    http, *_ = env
    put(http, [{"index": 0, "corrected_text": "យើងនៅមុខដំរី។"}, {"index": 1, "corrected_text": "នេះល្អ"}])
    s = http.get("/api/dataset/corrections").json()
    assert (s["pairs"], s["edited"], s["approved_unchanged"], s["jobs"]) == (2, 1, 1, 1)
    lines = http.get("/api/dataset/corrections", params={"format": "jsonl"}).text.strip().split("\n")
    row = json.loads(lines[0])
    assert row["source"].startswith("Here we are") and row["target"] == "យើងនៅមុខដំរី។" and row["edited"] is True


def test_trashed_jobs_are_excluded_and_purge_removes_corrections(env):
    http, Session, actor = env
    put(http, [{"index": 0, "corrected_text": "ក"}])
    http.delete("/api/jobs/j")
    assert http.get("/api/dataset/corrections").json()["pairs"] == 0
    actor.update(admin=True, user_id=None)
    http.delete("/api/trash/job/j")
    with Session() as s:
        assert s.scalars(select(TranslationCorrection)).all() == []


def test_training_split_keeps_videos_apart():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("ft", pathlib.Path(__file__).parents[1] / "training" / "finetune_mt.py")
    ft = importlib.util.module_from_spec(spec); spec.loader.exec_module(ft)
    rows = [{"job_id": f"v{v}", "source": f"s{v}{i}", "target": "ក"} for v in range(10) for i in range(10)]
    train, dev = ft.split_by_video(rows, 0.2, 1)
    assert len(dev) >= 20 and {r["job_id"] for r in train}.isdisjoint({r["job_id"] for r in dev})
    one = [{"job_id": "v", "source": f"s{i}", "target": "ក"} for i in range(10)]
    t, d = ft.split_by_video(one, 0.2, 1)
    assert len(d) == 2 and len(t) == 8
