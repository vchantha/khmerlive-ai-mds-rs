"""Output guards, retries, provider=none, smoke test and provenance of the offline LLM post-editor.

All network calls are mocked; real-model evidence comes from `python -m app.llm_postedit --smoke`.
"""
from dataclasses import dataclass
from types import SimpleNamespace
import httpx
import pytest
from app import llm_postedit
from app.llm_postedit import PostEditError, numbers_in, validate_khmer_line


@dataclass(frozen=True)
class Row:
    start_ms: int
    end_ms: int
    source_text: str
    target_text: str


def _settings(**overrides):
    values = dict(llm_postedit_enabled=True, vllm_postedit_enabled=False, llm_provider="ollama",
                  llm_base_url="http://ollama:11434/v1", llm_model="test", llm_timeout_seconds=30,
                  llm_max_tokens=128, llm_fail_open=True, llm_total_budget_seconds=900, llm_max_retries=0)
    values.update(overrides)
    return SimpleNamespace(**values)


def _client(replies):
    """Replies in order: str = completion, int = HTTP status error, Exception = raised."""
    calls = []
    class Response:
        def __init__(self, reply): self.reply = reply
        def raise_for_status(self):
            if isinstance(self.reply, int):
                req = httpx.Request("POST", "http://ollama:11434/v1/chat/completions")
                raise httpx.HTTPStatusError("err", request=req, response=httpx.Response(self.reply, request=req))
        def json(self): return {"choices": [{"message": {"content": self.reply}}]}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json, **kwargs):
            calls.append(json)
            reply = replies[len(calls) - 1]
            if isinstance(reply, Exception):
                raise reply
            return Response(reply)
    return Client, calls


# ---- numbers -------------------------------------------------------------
def test_numbers_normalize_khmer_digits_and_thousands():
    assert numbers_in("មាន ១២ មេរៀន និង 1,000 ដុល្លារ 2.5") == {"12", "1000", "2.5"}


def test_changed_number_is_rejected():
    # Real Qwen3-4B output seen on 2026-11-17: "50 dollars" became "5 dollars".
    with pytest.raises(PostEditError, match="dropped or changed number"):
        validate_khmer_line("វគ្គសិក្សានេះមាន 12 មេរៀន និងតម្លៃ 5 ដុល្លារ។",
                            "The course has 12 lessons and costs 50 dollars.",
                            "វគ្គសិក្សានេះមាន 12 មេរៀន និងតម្លៃ 50 ដុល្លារ។")


def test_number_in_khmer_digits_is_accepted():
    validate_khmer_line("វគ្គសិក្សានេះមាន ១២ មេរៀន។", "The course has 12 lessons.", "វគ្គសិក្សានេះមាន 12 មេរៀន។")


def test_invented_number_is_rejected():
    with pytest.raises(PostEditError, match="introduced number"):
        validate_khmer_line("ខ្ញុំមាន 3 ឆ្កែ", "I have dogs.", "ខ្ញុំមានឆ្កែ")


def test_number_draft_spelled_out_is_not_required():
    # Draft wrote the number in words; the LLM may too.
    validate_khmer_line("ខ្ញុំមានឆ្កែបីក្បាល", "I have 3 dogs.", "ខ្ញុំមានឆ្កែបី")


# ---- Khmer script / format ----------------------------------------------
@pytest.mark.parametrize("bad,reason", [
    ("", "empty"),
    ("This is still English text", "Khmer script"),
    ("Hello everyone, welcome ស", "mostly Latin"),
    ("ាសួស្តី", "dependent sign"),
    ("សួស្តី\nHello (greeting)", "several lines"),
    ("សួស្តី�", "invalid"),
    ("ស" * 400, "excessively long"),
])
def test_malformed_outputs_rejected(bad, reason):
    with pytest.raises(PostEditError, match=reason):
        validate_khmer_line(bad, "Hello", "សួស្តីអ្នកទាំងអស់គ្នា")


def test_much_shorter_output_rejected():
    with pytest.raises(PostEditError, match="much shorter"):
        validate_khmer_line("សួស្តី", "Hello everyone and welcome to the course",
                            "សួស្តីអ្នកទាំងអស់គ្នា និងសូមស្វាគមន៍មកកាន់វគ្គសិក្សា")


def test_latin_names_inside_khmer_allowed():
    validate_khmer_line("ការបណ្តុះបណ្តាល AI របស់យើង", "our AI training", "ការបណ្តុះបណ្តាល AI")


@pytest.mark.parametrize("raw", ['"សួស្តី"', "Khmer: សួស្តី", "```\nសួស្តី\n```", "```khmer\nសួស្តី\n```", "«សួស្តី»"])
def test_wrappers_removed(raw):
    assert llm_postedit._clean_output(raw, "ស", "hi") == "សួស្តី"


# ---- statuses, provider none --------------------------------------------
def test_unchanged_output_is_reported_as_unchanged(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    Client, _ = _client(["សួស្តី", "លាហើយ"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    report = []
    llm_postedit.postedit_rows([Row(0, 900, "hi", "សួស្តី"), Row(900, 1800, "bye", "លា")], "en", "km", report=report)
    assert [t["status"] for t in report] == ["unchanged", "edited"]


def test_provider_none_makes_no_call(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_provider="none"))
    class Boom:
        def __init__(self, **kw): raise AssertionError("no network for provider=none")
    monkeypatch.setattr(llm_postedit.httpx, "Client", Boom)
    rows = [Row(0, 900, "hi", "សួស្តី")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows
    st = llm_postedit.llm_status()
    assert st["status"] == "off" and "none" in st["detail"]


def test_invalid_provider_fail_closed(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_provider="openai", llm_fail_open=False))
    with pytest.raises(RuntimeError):
        llm_postedit.postedit_rows([Row(0, 900, "hi", "ស")], "en", "km")


# ---- retries ---------------------------------------------------------------
def test_transient_503_is_retried(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_max_retries=1))
    monkeypatch.setattr(llm_postedit.time, "sleep", lambda s: None)
    Client, calls = _client([503, "សួស្តីទាំងអស់គ្នា"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    out = llm_postedit.postedit_rows([Row(0, 900, "hi", "សួស្តី")], "en", "km")
    assert out[0].target_text == "សួស្តីទាំងអស់គ្នា" and len(calls) == 2


def test_timeout_retry_then_success(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_max_retries=2))
    monkeypatch.setattr(llm_postedit.time, "sleep", lambda s: None)
    Client, calls = _client([httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), "សួស្តីទាំងអស់គ្នា"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    assert llm_postedit.postedit_rows([Row(0, 900, "hi", "សួស្តី")], "en", "km")[0].target_text == "សួស្តីទាំងអស់គ្នា"
    assert len(calls) == 3


def test_client_error_400_not_retried(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_max_retries=3))
    Client, calls = _client([400, "សួស្តី"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "hi", "ស")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows and len(calls) == 1


def test_rejected_output_not_retried(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_max_retries=3))
    Client, calls = _client(["English only", "សួស្តី"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "hi", "ស")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows and len(calls) == 1


def test_retries_exhausted_keep_original(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_max_retries=1))
    monkeypatch.setattr(llm_postedit.time, "sleep", lambda s: None)
    Client, calls = _client([502, 502])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "hi", "ស")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows and len(calls) == 2


# ---- multi-segment with mixed outcomes, parallel path --------------------
@pytest.mark.parametrize("concurrency", [1, 3])
def test_multi_segment_mixed_outcomes_preserve_timestamps(monkeypatch, concurrency):
    monkeypatch.setattr(llm_postedit, "settings", _settings(llm_concurrency=concurrency))
    rows = [Row(0, 1000, "I paid 50 dollars.", "ខ្ញុំបានបង់ 50 ដុល្លារ។"),
            Row(1000, 2500, "Hello", "សួស្តី"),
            Row(2500, 4000, "Bye", "លា")]
    by_source = {"I paid 50 dollars.": "ខ្ញុំបានបង់ 5 ដុល្លារ។",   # changed number -> rejected
                 "Hello": "សួស្តីអ្នកទាំងអស់គ្នា", "Bye": "លាហើយ"}
    class Response:
        def __init__(self, c): self.c = c
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": self.c}}]}
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json, **kw):
            import json as j
            return Response(by_source[j.loads(json["messages"][1]["content"])["english"]])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    report = []
    out = llm_postedit.postedit_rows(rows, "en", "km", report=report)
    assert [r.target_text for r in out] == ["ខ្ញុំបានបង់ 50 ដុល្លារ។", "សួស្តីអ្នកទាំងអស់គ្នា", "លាហើយ"]
    assert [(r.start_ms, r.end_ms) for r in out] == [(r.start_ms, r.end_ms) for r in rows]
    assert report[0]["status"] == "kept original (rejected output)" and "50" in report[0]["error"]


# ---- provenance & smoke test --------------------------------------------
def test_prompt_version_tracks_prompt_text(monkeypatch):
    v1 = llm_postedit.prompt_version("polish")
    assert v1.startswith("polish-") and v1 != llm_postedit.prompt_version("translate")
    monkeypatch.setattr(llm_postedit, "SYSTEM_PROMPT", llm_postedit.SYSTEM_PROMPT + " changed")
    assert llm_postedit.prompt_version("polish") != v1


def test_smoke_reports_missing_model_without_inference(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    monkeypatch.setattr(llm_postedit, "llm_status", lambda: {"provider": "ollama", "model": "test", "prompt_version": "p",
                                                             "status": "model_missing", "detail": "Model 'test' is not on the ollama server"})
    res = llm_postedit.llm_smoke_test()
    assert res["ok"] is False and "not on the ollama server" in res["error"]


def test_smoke_runs_real_request_through_guards(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    monkeypatch.setattr(llm_postedit, "llm_status", lambda: {"provider": "ollama", "model": "test", "prompt_version": "p", "status": "ready"})
    Client, calls = _client(["វគ្គសិក្សានេះមាន 12 មេរៀន។"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    res = llm_postedit.llm_smoke_test()
    assert res["ok"] is True and res["output"] and len(calls) == 1


def test_smoke_fails_when_guard_rejects(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _settings())
    monkeypatch.setattr(llm_postedit, "llm_status", lambda: {"provider": "ollama", "model": "test", "prompt_version": "p", "status": "ready"})
    Client, _ = _client(["វគ្គសិក្សានេះមាន 2 មេរៀន។"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    res = llm_postedit.llm_smoke_test()
    assert res["ok"] is False and "number" in res["error"]
