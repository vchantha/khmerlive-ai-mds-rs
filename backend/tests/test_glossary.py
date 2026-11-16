"""Glossary matching, translate-mode prompt, required-term retry and glossary API."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app import llm_postedit
from app.db import Base
from app.glossary import Term, missing_terms, terms_for
from app.real_inference import TimedText

ELEPHANT, TRUNK, ICE, ICECREAM = Term("elephant", "ដំរី"), Term("trunk", "ប្រមោយ"), Term("ice", "ទឹកកក"), Term("ice cream", "ការ៉េម")


def test_matching_whole_words_plurals_and_case():
    assert terms_for("Here we are in front of the Elephants.", [ELEPHANT]) == [ELEPHANT]
    assert terms_for("really long trunks,", [TRUNK, ELEPHANT]) == [TRUNK]
    assert terms_for("an elephantine task", [ELEPHANT]) == []          # not a whole word
    assert terms_for("I like ice cream", [ICE, ICECREAM]) == [ICECREAM]  # longest match wins


def test_missing_terms():
    assert missing_terms("យើងនៅមុខដំរី", [ELEPHANT]) == []
    assert missing_terms("យើងនៅមុខអ៊ីនធឺណិត", [ELEPHANT]) == [ELEPHANT]


def _settings(**kw):
    base = dict(llm_postedit_enabled=True, vllm_postedit_enabled=False, llm_provider="ollama",
                llm_base_url="http://ollama:11434/v1", llm_model="m", llm_timeout_seconds=30, llm_max_tokens=128,
                llm_fail_open=True, llm_total_budget_seconds=900, llm_concurrency=1, llm_mode="translate")
    base.update(kw)
    return SimpleNamespace(**base)


def _client(replies, sent):
    it = iter(replies)
    class Client:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json, **k):
            sent.append(json)
            c = next(it)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": c}}]})
    return Client


ROWS = [TimedText(0, 3000, "All right, so here we are, in front of the elephants.", "អ៊ីនធឺណិត"),
        TimedText(3000, 6000, "And that's cool.", "នេះល្អ")]


@pytest.mark.parametrize("concurrency", [1, 2])
def test_translate_mode_sends_context_draft_and_required_terms(monkeypatch, concurrency):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_concurrency=concurrency))
    sent = []
    monkeypatch.setattr(llm_postedit.httpx, "Client", _client(["យើងនៅមុខដំរី។", "ឡូយ។"], sent))
    report = []
    out = llm_postedit.postedit_rows(ROWS, "en", "km", report=report, terms=[ELEPHANT, TRUNK])
    first = next(json.loads(p["messages"][1]["content"]) for p in sent
                 if "elephants" in json.loads(p["messages"][1]["content"])["english"])
    assert first["required_terms"] == {"elephant": "ដំរី"}
    assert first["machine_draft_may_be_wrong"] == "អ៊ីនធឺណិត" and first["next_line"] == "And that's cool."
    assert sent[0]["messages"][0]["content"] == llm_postedit.TRANSLATE_PROMPT
    assert out[0].target_text == "យើងនៅមុខដំរី។"
    assert sorted(t["status"] for t in report) == ["edited", "edited"]


def test_missing_required_term_triggers_one_retry(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    sent = []
    monkeypatch.setattr(llm_postedit.httpx, "Client", _client(["នៅមុខអ៊ីនធឺណិត។", "យើងនៅមុខដំរី។", "ឡូយ។"], sent))
    report = []
    out = llm_postedit.postedit_rows(ROWS, "en", "km", report=report, terms=[ELEPHANT])
    assert len(sent) == 3 and "ដំរី" in sent[1]["messages"][-1]["content"]
    assert out[0].target_text == "យើងនៅមុខដំរី។" and report[0]["status"] == "edited"


def test_term_still_missing_is_reported(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    monkeypatch.setattr(llm_postedit.httpx, "Client", _client(["អ៊ីនធឺណិត។", "អ៊ីនធឺណិត។", "ឡូយ។"], []))
    report = []
    llm_postedit.postedit_rows(ROWS, "en", "km", report=report, terms=[ELEPHANT])
    assert report[0]["status"] == "edited (missing term: elephant)"


def test_polish_mode_keeps_previous_prompt(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_mode="polish"))
    sent = []
    monkeypatch.setattr(llm_postedit.httpx, "Client", _client(["ក", "ខ"], sent))
    llm_postedit.postedit_rows(ROWS, "en", "km")
    assert sent[0]["messages"][0]["content"] == llm_postedit.SYSTEM_PROMPT
    assert "draft_khmer" in json.loads(sent[0]["messages"][1]["content"])


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def session():
        with Session() as s:
            yield s
    monkeypatch.setattr(main, "session", session)
    actor = {"admin": True, "user_id": None}
    main.app.dependency_overrides[main.authorize] = lambda: actor
    with TestClient(main.app) as http:
        yield http, actor
    main.app.dependency_overrides.clear()


def test_glossary_api_add_update_list_delete(api):
    http, _ = api
    r = http.post("/api/glossary", json={"source_term": "  Elephant ", "target_term": "ដំរី"})
    assert r.status_code == 201 and r.json()["source_term"] == "elephant"
    http.post("/api/glossary", json={"source_term": "elephant", "target_term": "សត្វដំរី"})     # same term -> update
    items = http.get("/api/glossary").json()["items"]
    assert len(items) == 1 and items[0]["target_term"] == "សត្វដំរី"
    assert http.get("/api/glossary", params={"search": "eleph"}).json()["items"]
    assert http.delete(f"/api/glossary/{items[0]['id']}").status_code == 200
    assert http.get("/api/glossary").json()["items"] == []


def test_glossary_validation_and_admin_only(api):
    http, actor = api
    assert http.post("/api/glossary", json={"source_term": "elephant", "target_term": "elephant"}).status_code == 422
    actor.update(admin=False, user_id="u1")
    assert http.post("/api/glossary", json={"source_term": "x", "target_term": "ក"}).status_code == 403
    assert http.get("/api/glossary").status_code == 200        # everyone can read it


def test_polish_mode_enforces_glossary_and_retries(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_mode="polish"))
    sent = []
    monkeypatch.setattr(llm_postedit.httpx, "Client", _client(["នៅមុខអ៊ីនធឺណិត។", "យើងនៅមុខដំរី។", "ឡូយ។"], sent))
    report = []
    out = llm_postedit.postedit_rows(ROWS, "en", "km", report=report, terms=[ELEPHANT])
    body = json.loads(sent[0]["messages"][1]["content"])
    assert body["required_terms"] == {"elephant": "ដំរី"} and "required_terms" in sent[0]["messages"][0]["content"]
    assert "ដំរី" in sent[1]["messages"][-1]["content"]          # retry insists on the term
    assert out[0].target_text == "យើងនៅមុខដំរី។" and report[0]["status"] == "edited"
