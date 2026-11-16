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
        def post(self, url, json):
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
        def post(self, url, json):
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
        def post(self, url, json):
            raise httpx.ReadTimeout("offline timeout")
    monkeypatch.setattr(llm_postedit.httpx, "Client", Client)
    rows = [Row(0, 900, "Hello", "សួស្តី")]
    assert llm_postedit.postedit_rows(rows, "en", "km") is rows

def test_reject_public_endpoint():
    with pytest.raises(ValueError):
        llm_postedit.validate_local_endpoint("http://example.org:11434/v1")
