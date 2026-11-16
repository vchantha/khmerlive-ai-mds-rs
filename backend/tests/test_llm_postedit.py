from dataclasses import dataclass
from types import SimpleNamespace
import pytest
from app import llm_postedit

@dataclass(frozen=True)
class Row:
    start_ms: int
    end_ms: int
    source_text: str
    target_text: str

def test_disabled_does_not_call_network(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", SimpleNamespace(llm_postedit_enabled=False, vllm_postedit_enabled=False))
    rows = [Row(0, 1000, "Hello", "សួស្តី")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows

@pytest.mark.parametrize("url", ["https://example.com/v1", "http://169.254.169.254/v1", "http://vllm:8000/v1/extra", "http://user:pass@vllm:8000/v1"])
def test_reject_unsafe_endpoints(url):
    with pytest.raises(ValueError):
        llm_postedit.validate_local_endpoint(url)

def test_valid_endpoint():
    assert llm_postedit.validate_local_endpoint("http://vllm:8000/v1/") == "http://vllm:8000/v1"

def test_postedit_preserves_timestamps(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", SimpleNamespace(llm_postedit_enabled=False, vllm_postedit_enabled=True, vllm_base_url="http://vllm:8000/v1", vllm_model="test", vllm_timeout_seconds=3, vllm_max_tokens=100, vllm_fail_open=False))
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"choices":[{"message":{"content":"សួស្តីអ្នកទាំងអស់គ្នា"}}]}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, **kwargs):
            assert url == "http://vllm:8000/v1/chat/completions"
            return Response()
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(100, 900, "Hello everyone", "សួស្តី")]
    result = llm_postedit.postedit_rows(rows, "en", "km")
    assert result[0].start_ms == 100 and result[0].end_ms == 900
    assert result[0].target_text == "សួស្តីអ្នកទាំងអស់គ្នា"
    assert rows[0].target_text == "សួស្តី"

def test_ollama_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", SimpleNamespace(
        llm_postedit_enabled=True, vllm_postedit_enabled=False,
        llm_provider="ollama", llm_base_url="http://ollama:11434/v1",
        llm_model="qwen3:4b-instruct", llm_timeout_seconds=180,
        llm_max_tokens=128, llm_fail_open=False,
    ))
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "សួស្តីអ្នកទាំងអស់គ្នា"}}]}
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, **kwargs):
            assert url == "http://ollama:11434/v1/chat/completions"
            assert json["model"] == "qwen3:4b-instruct"
            return Response()
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(100, 900, "Hello everyone", "សួស្តី")]
    edited = llm_postedit.postedit_rows(rows, "en", "km")
    assert edited[0].target_text == "សួស្តីអ្នកទាំងអស់គ្នា"
    assert edited[0].start_ms == 100 and edited[0].end_ms == 900

def test_ollama_timeout_falls_back_to_original(monkeypatch):
    import httpx
    monkeypatch.setattr(llm_postedit, "settings", SimpleNamespace(
        llm_postedit_enabled=True, vllm_postedit_enabled=False,
        llm_provider="ollama", llm_base_url="http://ollama:11434/v1",
        llm_model="test", llm_timeout_seconds=1,
        llm_max_tokens=128, llm_fail_open=True,
    ))
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, **kwargs):
            raise httpx.ReadTimeout("offline timeout")
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "Hello", "សួស្តី")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows

def test_reject_public_endpoint():
    with pytest.raises(ValueError):
        llm_postedit.validate_local_endpoint("http://example.org:11434/v1")


def _ollama_settings(**overrides):
    values = dict(
        llm_postedit_enabled=True, vllm_postedit_enabled=False,
        llm_provider="ollama", llm_base_url="http://ollama:11434/v1",
        llm_model="test", llm_timeout_seconds=30,
        llm_max_tokens=128, llm_fail_open=True, llm_total_budget_seconds=900,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _scripted_client(replies):
    """Fake httpx.Client returning replies in order; an Exception reply is raised."""
    calls = []
    class Response:
        def __init__(self, content): self.content = content
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": self.content}}]}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, **kwargs):
            calls.append(kwargs)
            reply = replies[len(calls) - 1]
            if isinstance(reply, Exception):
                raise reply
            return Response(reply)
    return Client, calls


def test_one_bad_segment_keeps_other_edits(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _ollama_settings())
    Client, calls = _scripted_client(["កខ", "English only", "គឃ"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "a", "ក"), Row(900, 1800, "b", "ខ"), Row(1800, 2700, "c", "គ")]
    edited = llm_postedit.postedit_rows(rows, "en", "km")
    assert [r.target_text for r in edited] == ["កខ", "ខ", "គឃ"]
    assert len(calls) == 3


def test_segment_timeout_only_reverts_that_segment(monkeypatch):
    import httpx
    monkeypatch.setattr(llm_postedit, "settings", _ollama_settings())
    Client, _ = _scripted_client([httpx.ReadTimeout("slow"), "កគ"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "a", "ក"), Row(900, 1800, "b", "ខ")]
    assert [r.target_text for r in llm_postedit.postedit_rows(rows, "en", "km")] == ["ក", "កគ"]


def test_unreachable_server_stops_after_first_attempt(monkeypatch):
    import httpx
    monkeypatch.setattr(llm_postedit, "settings", _ollama_settings())
    Client, calls = _scripted_client([httpx.ConnectError("refused")] * 3)
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "a", "ក"), Row(900, 1800, "b", "ខ"), Row(1800, 2700, "c", "គ")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows
    assert len(calls) == 1


def test_fail_closed_raises_on_segment_failure(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _ollama_settings(llm_fail_open=False))
    Client, _ = _scripted_client(["English only"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    with pytest.raises(RuntimeError):
        llm_postedit.postedit_rows([Row(0, 900, "a", "ក")], "en", "km")


def test_budget_exhaustion_leaves_remaining_segments(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _ollama_settings(llm_total_budget_seconds=100))
    clock = iter([0.0, 0.0, 200.0, 200.0])
    monkeypatch.setattr(llm_postedit.time, "monotonic", lambda: next(clock))
    Client, calls = _scripted_client(["កខ", "កគ"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "a", "ក"), Row(900, 1800, "b", "ខ")]
    assert [r.target_text for r in llm_postedit.postedit_rows(rows, "en", "km")] == ["កខ", "ខ"]
    assert len(calls) == 1
    assert calls[0]["timeout"] <= 30


def test_budget_exhaustion_fail_closed_raises(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _ollama_settings(llm_total_budget_seconds=0, llm_fail_open=False))
    with pytest.raises(RuntimeError):
        llm_postedit.postedit_rows([Row(0, 900, "a", "ក")], "en", "km")


@pytest.mark.parametrize("raw", [
    "<think>The user wants Khmer. ក is a letter.</think>\nសួស្តី",
    "<THINK>\nreasoning\n</THINK>សួស្តី",
])
def test_reasoning_tags_are_stripped(monkeypatch, raw):
    monkeypatch.setattr(llm_postedit, "settings", _ollama_settings())
    Client, _ = _scripted_client([raw])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    assert llm_postedit.postedit_rows([Row(0, 900, "hi", "ស")], "en", "km")[0].target_text == "សួស្តី"


def test_unterminated_reasoning_is_rejected(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _ollama_settings())
    Client, _ = _scripted_client(["<think>ក still thinking and ran out of tokens"])
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "hi", "ស")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows


def _status_settings(**kw):
    base = dict(llm_postedit_enabled=False, vllm_postedit_enabled=False, llm_provider="ollama",
                llm_base_url="http://ollama:11434/v1", llm_model="qwen3:4b-instruct",
                llm_timeout_seconds=180, llm_max_tokens=128, llm_fail_open=True)
    base.update(kw)
    return SimpleNamespace(**base)

_TAGS = "http://ollama:11434/api/tags"
_PS = "http://ollama:11434/api/ps"

def _probe_client(payload=None, error=None, expect_url=None, routes=None):
    """routes maps url -> payload (or Exception); otherwise every GET returns payload."""
    class Response:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data
    class Client:
        def __init__(self, **kwargs): assert kwargs["trust_env"] is False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            if routes is not None:
                assert url in routes, url
                if isinstance(routes[url], Exception): raise routes[url]
                return Response(routes[url])
            if expect_url: assert url == expect_url
            if error: raise error
            return Response(payload)
    return Client

def test_status_ready_when_ollama_model_pulled(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings(llm_postedit_enabled=True))
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client(routes={
        _TAGS: {"models": [{"name": "qwen3:4b-instruct"}]}, _PS: {"models": []}}))
    s = llm_postedit.llm_status()
    assert s["status"] == "ready" and s["server"] == "online" and s["model_available"] is True

def test_status_model_missing(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings(llm_postedit_enabled=True))
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client({"models": []}))
    assert llm_postedit.llm_status()["status"] == "model_missing"

def test_status_offline_when_enabled(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings(llm_postedit_enabled=True))
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client(error=llm_postedit.httpx.ConnectError("x")))
    s = llm_postedit.llm_status()
    assert s["status"] == "offline" and s["server"] == "offline"

def test_status_off_still_reports_server(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings())
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client({"models": [{"name": "qwen3:4b-instruct"}]}))
    s = llm_postedit.llm_status()
    assert s["status"] == "off" and s["enabled"] is False and s["model_available"] is True

def test_status_vllm_models_endpoint(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings(
        vllm_postedit_enabled=True, vllm_base_url="http://vllm:8000/v1", vllm_model="khmerlive-postedit",
        vllm_timeout_seconds=60, vllm_max_tokens=256, vllm_fail_open=True))
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client(
        {"data": [{"id": "khmerlive-postedit"}]}, expect_url="http://vllm:8000/v1/models"))
    assert llm_postedit.llm_status()["status"] == "ready"

def test_untagged_model_matches_latest():
    assert llm_postedit._model_matches("qwen3", ["qwen3:latest"])
    assert not llm_postedit._model_matches("qwen3:4b", ["qwen3:latest"])

def _loaded(size, vram, name="qwen3:4b-instruct"):
    return {_TAGS: {"models": [{"name": "qwen3:4b-instruct"}]},
            _PS: {"models": [{"name": name, "size": size, "size_vram": vram}]}}

@pytest.mark.parametrize("size,vram,processor,pct", [
    (3_000, 3_000, "gpu", 100), (3_000, 0, "cpu", 0), (3_000, 1_500, "split", 50)])
def test_status_reports_ollama_processor(monkeypatch, size, vram, processor, pct):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings(llm_postedit_enabled=True))
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client(routes=_loaded(size, vram)))
    s = llm_postedit.llm_status()
    assert s["processor"] == processor and s["gpu_percent"] == pct

def test_status_processor_idle_when_model_not_loaded(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings(llm_postedit_enabled=True))
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client(routes=_loaded(3_000, 3_000, name="other:1b")))
    s = llm_postedit.llm_status()
    assert s["processor"] == "idle" and s["gpu_percent"] is None and s["status"] == "ready"

def test_status_processor_probe_failure_is_non_fatal(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings(llm_postedit_enabled=True))
    routes = {_TAGS: {"models": [{"name": "qwen3:4b-instruct"}]}, _PS: llm_postedit.httpx.ConnectError("x")}
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client(routes=routes))
    s = llm_postedit.llm_status()
    assert s["status"] == "ready" and s["processor"] is None

def test_status_vllm_is_gpu(monkeypatch):
    monkeypatch.setattr(llm_postedit, "settings", _status_settings(
        vllm_postedit_enabled=True, vllm_base_url="http://vllm:8000/v1", vllm_model="khmerlive-postedit",
        vllm_timeout_seconds=60, vllm_max_tokens=256, vllm_fail_open=True))
    monkeypatch.setattr(llm_postedit.httpx, "Client", _probe_client({"data": [{"id": "khmerlive-postedit"}]}))
    assert llm_postedit.llm_status()["processor"] == "gpu"
