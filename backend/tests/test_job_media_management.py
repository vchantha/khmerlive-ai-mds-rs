"""Delete / search / sort routes for jobs and source videos.

Runs the real SQLAlchemy queries against in-memory SQLite and a fake S3 client,
so no PostgreSQL or MinIO is needed.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.db import Base
from app.models import AppUser, MediaAsset, TranslationJob

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


class FakeS3:
    def __init__(self, fail=False):
        self.deleted, self.fail = [], fail

    def delete_objects(self, Bucket, Delete):
        if self.fail:
            raise RuntimeError("minio down")
        self.deleted += [o["Key"] for o in Delete["Objects"]]


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def session():
        with Session() as db:
            yield db

    s3 = FakeS3()
    actor = {"admin": True, "user_id": None}
    monkeypatch.setattr(main, "session", session)
    monkeypatch.setattr(main, "client", lambda: s3)
    main.app.dependency_overrides[main.authorize] = lambda: actor

    with Session() as db:
        db.add_all([AppUser(id="u1", display_name="One"), AppUser(id="u2", display_name="Two")])
        media = [("m1", "Zebra news.mp4", 300, "upload", "u1", 0),
                 ("m2", "apple 100%_off.mp4", 100, "youtube", "u1", 1),
                 ("m3", "Mango.mp4", 200, "url", "u2", 2)]
        for mid, name, size, kind, owner, day in media:
            db.add(MediaAsset(id=mid, filename=name, object_key=f"uploads/{mid}.mp4", content_type="video/mp4",
                              size_bytes=size, sha256="0" * 64, source_kind=kind, owner_user_id=owner,
                              source_url="https://youtu.be/abc" if kind == "youtube" else None,
                              created_at=T0 + timedelta(days=day)))
        jobs = [("j1", "m1", "completed", "u1", 0, "outputs/j1.mp4", "outputs/j1.srt"),
                ("j2", "m1", "processing", "u1", 1, None, None),
                ("j3", "m2", "failed", "u1", 2, None, None),
                ("j4", "m3", "completed", "u2", 3, "outputs/j4.mp4", None)]
        for jid, mid, status, owner, day, out, sub in jobs:
            db.add(TranslationJob(id=jid, media_id=mid, source_lang="en", target_lang="km", status=status,
                                  owner_user_id=owner, output_key=out, subtitle_key=sub, cancel_requested=False,
                                  created_at=T0 + timedelta(days=day), updated_at=T0 + timedelta(days=day)))
        db.commit()

    with TestClient(main.app) as http:
        yield http, s3, actor, Session
    main.app.dependency_overrides.clear()


def ids(r):
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]]


# ---- jobs: sort / search ----

@pytest.mark.parametrize("sort,expected", [
    ("newest", ["j4", "j3", "j2", "j1"]),
    ("oldest", ["j1", "j2", "j3", "j4"]),
    ("name_asc", ["j3", "j4", "j2", "j1"]),   # apple, Mango, Zebra (newest first within)
    ("name_desc", ["j2", "j1", "j4", "j3"]),
])
def test_jobs_sort(env, sort, expected):
    http, *_ = env
    assert ids(http.get("/api/jobs", params={"sort": sort})) == expected


def test_jobs_rejects_unknown_sort(env):
    http, *_ = env
    assert http.get("/api/jobs", params={"sort": "id; drop table"}).status_code == 422


def test_jobs_search_is_case_insensitive_and_literal(env):
    http, *_ = env
    assert ids(http.get("/api/jobs", params={"search": "zebra"})) == ["j2", "j1"]
    # % and _ match literally instead of acting as wildcards.
    assert ids(http.get("/api/jobs", params={"search": "100%_"})) == ["j3"]
    assert ids(http.get("/api/jobs", params={"search": "%"})) == ["j3"]
    assert ids(http.get("/api/jobs", params={"search": "youtu.be"})) == ["j3"]


def test_jobs_filter_by_media(env):
    http, *_ = env
    assert ids(http.get("/api/jobs", params={"media_id": "m1"})) == ["j2", "j1"]


# ---- jobs: delete moves to Trash ----

def test_delete_job_moves_it_to_trash_and_keeps_files(env):
    http, s3, actor, Session = env
    actor.update(admin=False, user_id="u1")
    r = http.delete("/api/jobs/j1")
    assert r.status_code == 200 and r.json()["trashed"] is True
    assert s3.deleted == []                                    # nothing erased yet
    with Session() as db:
        j = db.get(TranslationJob, "j1")
        assert j is not None and j.deleted_at is not None and j.deleted_by == "u1"
    # Hidden from the owner's lists, detail, download and counts.
    assert "j1" not in ids(http.get("/api/jobs"))
    assert http.get("/api/jobs/j1").status_code == 404
    assert http.get("/api/jobs/j1/download").status_code == 404
    assert http.get("/api/dashboard").json()["completed"] == 0


def test_delete_active_job_is_refused(env):
    http, _, _, Session = env
    assert http.delete("/api/jobs/j2").status_code == 409
    with Session() as db:
        assert db.get(TranslationJob, "j2").deleted_at is None


def test_delete_job_owned_by_someone_else_is_404(env):
    http, _, actor, Session = env
    actor.update(admin=False, user_id="u1")
    assert http.delete("/api/jobs/j4").status_code == 404
    with Session() as db:
        assert db.get(TranslationJob, "j4").deleted_at is None


def test_deleting_twice_is_404(env):
    http, *_ = env
    assert http.delete("/api/jobs/j1").status_code == 200
    assert http.delete("/api/jobs/j1").status_code == 404


# ---- videos: list / search / sort ----

def test_media_list_counts_jobs(env):
    http, *_ = env
    items = {i["id"]: i for i in http.get("/api/media").json()["items"]}
    assert (items["m1"]["jobs"], items["m1"]["active"], items["m1"]["completed"]) == (2, 1, 1)
    assert (items["m2"]["jobs"], items["m2"]["active"]) == (1, 0)


@pytest.mark.parametrize("sort,expected", [
    ("newest", ["m3", "m2", "m1"]), ("oldest", ["m1", "m2", "m3"]),
    ("name_asc", ["m2", "m3", "m1"]), ("size_desc", ["m1", "m3", "m2"]), ("size_asc", ["m2", "m3", "m1"]),
])
def test_media_sort(env, sort, expected):
    http, *_ = env
    assert ids(http.get("/api/media", params={"sort": sort})) == expected


def test_media_search_and_source_filter(env):
    http, *_ = env
    assert ids(http.get("/api/media", params={"search": "MANGO"})) == ["m3"]
    assert ids(http.get("/api/media", params={"source": "youtube"})) == ["m2"]


def test_media_list_is_scoped_to_owner(env):
    http, _, actor, _ = env
    actor.update(admin=False, user_id="u2")
    assert ids(http.get("/api/media")) == ["m3"]


def test_media_counts_ignore_trashed_jobs(env):
    http, *_ = env
    http.delete("/api/jobs/j1")
    m1 = next(i for i in http.get("/api/media").json()["items"] if i["id"] == "m1")
    assert (m1["jobs"], m1["completed"]) == (1, 0)


# ---- videos: delete moves to Trash ----

def test_delete_video_trashes_it_with_its_jobs(env):
    http, s3, _, Session = env
    r = http.delete("/api/media/m3")
    assert r.status_code == 200 and r.json()["jobs_trashed"] == 1
    assert s3.deleted == []
    with Session() as db:
        m, j = db.get(MediaAsset, "m3"), db.get(TranslationJob, "j4")
        assert m.deleted_at is not None and j.deleted_at == m.deleted_at
    assert "m3" not in ids(http.get("/api/media"))
    assert "j4" not in ids(http.get("/api/jobs"))


def test_trashed_video_cannot_get_new_jobs(env, monkeypatch):
    http, *_ = env
    monkeypatch.setattr(main, "ensure_translation_ready", lambda lang: None)
    http.delete("/api/media/m3")
    r = http.post("/api/jobs", json={"media_id": "m3", "source_lang": "en", "target_lang": "km"})
    assert r.status_code == 404


def test_delete_video_with_active_job_is_refused(env):
    http, _, _, Session = env
    assert http.delete("/api/media/m1").status_code == 409
    with Session() as db:
        assert db.get(MediaAsset, "m1").deleted_at is None and db.get(TranslationJob, "j1").deleted_at is None


def test_delete_video_owned_by_someone_else_is_404(env):
    http, _, actor, Session = env
    actor.update(admin=False, user_id="u1")
    assert http.delete("/api/media/m3").status_code == 404


# ---- Trash (admin only) ----

def test_trash_is_admin_only(env):
    http, _, actor, _ = env
    actor.update(admin=False, user_id="u1")
    assert http.get("/api/trash").status_code == 403
    assert http.delete("/api/trash").status_code == 403
    assert http.post("/api/trash/job/j1/restore").status_code == 403
    assert http.delete("/api/trash/job/j1").status_code == 403


def test_trash_lists_user_deletions_for_admin(env):
    http, _, actor, _ = env
    actor.update(admin=False, user_id="u1"); http.delete("/api/jobs/j3")
    actor.update(admin=True, user_id=None); http.delete("/api/media/m3")
    items = http.get("/api/trash").json()["items"]
    assert [(i["kind"], i["id"]) for i in items] == [("video", "m3"), ("job", "j3")]   # newest first
    assert items[1]["deleted_by_name"] == "One" and items[0]["deleted_by_name"] == "Administrator"
    assert items[0]["jobs"] == 1                       # j4 is listed under its video, not separately
    assert [i["id"] for i in http.get("/api/trash", params={"kind": "job"}).json()["items"]] == ["j3"]
    assert [i["id"] for i in http.get("/api/trash", params={"search": "mango"}).json()["items"]] == ["m3"]


def test_restore_job_brings_it_back(env):
    http, _, _, Session = env
    http.delete("/api/jobs/j1")
    assert http.post("/api/trash/job/j1/restore").status_code == 200
    assert "j1" in ids(http.get("/api/jobs"))
    assert http.get("/api/trash").json()["items"] == []


def test_restore_video_restores_jobs_trashed_with_it_only(env):
    http, _, _, Session = env
    http.delete("/api/jobs/j4")          # trashed on its own first
    http.delete("/api/media/m3")         # then the video (no live jobs left)
    r = http.post("/api/trash/video/m3/restore")
    assert r.status_code == 200 and r.json()["jobs_restored"] == 0
    with Session() as db:
        assert db.get(TranslationJob, "j4").deleted_at is not None   # stays in Trash


def test_restore_job_also_restores_its_trashed_video(env):
    http, _, _, Session = env
    http.delete("/api/media/m3")
    assert http.post("/api/trash/job/j4/restore").status_code == 200
    with Session() as db:
        assert db.get(MediaAsset, "m3").deleted_at is None


def test_purge_job_permanently_deletes_row_and_files(env):
    http, s3, _, Session = env
    http.delete("/api/jobs/j1")
    r = http.delete("/api/trash/job/j1")
    assert r.status_code == 200 and r.json()["storage_cleaned"] is True
    assert sorted(s3.deleted) == ["outputs/j1.mp4", "outputs/j1.srt"]
    with Session() as db:
        assert db.get(TranslationJob, "j1") is None and db.get(MediaAsset, "m1") is not None


def test_purge_requires_item_in_trash(env):
    http, s3, _, Session = env
    assert http.delete("/api/trash/job/j1").status_code == 404
    assert http.delete("/api/trash/video/m3").status_code == 404
    assert s3.deleted == []


def test_empty_trash_purges_everything_trashed(env):
    http, s3, _, Session = env
    http.delete("/api/jobs/j1"); http.delete("/api/media/m3")
    r = http.delete("/api/trash")
    assert r.status_code == 200
    assert (r.json()["jobs_deleted"], r.json()["videos_deleted"]) == (2, 1)
    assert sorted(s3.deleted) == ["outputs/j1.mp4", "outputs/j1.srt", "outputs/j4.mp4", "uploads/m3.mp4"]
    with Session() as db:
        assert db.get(TranslationJob, "j1") is None and db.get(MediaAsset, "m3") is None
        assert db.get(TranslationJob, "j2") is not None and db.get(MediaAsset, "m1") is not None
    assert http.get("/api/trash").json()["total"] == 0


def test_empty_trash_still_succeeds_when_storage_is_down(env):
    http, s3, _, Session = env
    http.delete("/api/jobs/j1"); s3.fail = True
    r = http.delete("/api/trash")
    assert r.status_code == 200 and r.json()["storage_cleaned"] is False
    with Session() as db:
        assert db.get(TranslationJob, "j1") is None
