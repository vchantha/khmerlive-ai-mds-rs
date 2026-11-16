"""Optional offline Ollama/vLLM post-editing of timestamped English→Khmer segments.

The service is only called when explicitly enabled. Never send user text to
a public endpoint: the configured endpoint must be an internal Docker hostname.
"""
import json
import logging
from dataclasses import replace
from urllib.parse import urlsplit
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

def validate_local_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("vLLM must use an internal HTTP endpoint")
    if parsed.hostname not in {"vllm", "ollama", "localhost", "127.0.0.1"}:
        raise ValueError("vLLM endpoint must be a trusted local service")
    if parsed.path.rstrip("/") not in {"", "/v1"}:
        raise ValueError("vLLM endpoint must end at /v1")
    return url.rstrip("/")

def postedit_rows(rows, source_lang: str, target_lang: str):
    """Return unchanged rows unless explicitly enabled for English→Khmer."""
    if not (settings.llm_postedit_enabled or settings.vllm_postedit_enabled) or source_lang != "en" or target_lang != "km":
        return rows
    try:
        provider = settings.llm_provider if settings.llm_postedit_enabled else "vllm"
        if provider not in {"ollama", "vllm"}:
            raise ValueError("Unsupported offline LLM provider")
        endpoint = validate_local_endpoint(settings.llm_base_url if settings.llm_postedit_enabled else settings.vllm_base_url)
        if provider == "ollama" and urlsplit(endpoint).hostname not in {"ollama", "localhost", "127.0.0.1"}:
            raise ValueError("Ollama provider must use an Ollama endpoint")
        edited = []
        with httpx.Client(timeout=settings.llm_timeout_seconds if settings.llm_postedit_enabled else settings.vllm_timeout_seconds, trust_env=False) as client:
            for row in rows:
                if not row.target_text.strip():
                    edited.append(row)
                    continue
                payload = {
                    "model": settings.llm_model if settings.llm_postedit_enabled else settings.vllm_model,
                    "temperature": 0,
                    "max_tokens": settings.llm_max_tokens if settings.llm_postedit_enabled else settings.vllm_max_tokens,
                    "messages": [
                        {"role": "system", "content": (
                            "You are a careful English-to-Khmer translation post-editor for video dubbing. "
                            "Improve Khmer fluency without adding or deleting facts, numbers, names, or meaning. "
                            "Keep the result concise and speakable. Return only the revised Khmer translation."
                        )},
                        {"role": "user", "content": json.dumps({
                            "english": row.source_text,
                            "draft_khmer": row.target_text,
                            "available_duration_ms": row.end_ms - row.start_ms
                        }, ensure_ascii=False)}
                    ],
                }
                response = client.post(endpoint + "/chat/completions", json=payload)
                response.raise_for_status()
                result = response.json()["choices"][0]["message"]["content"]
                if not isinstance(result, str):
                    raise ValueError("vLLM response content must be text")
                result = result.strip()
                # Basic output guard; human evaluation remains necessary.
                if not result or len(result) > max(150, len(row.target_text) * 3):
                    raise ValueError("vLLM returned empty or excessively long output")
                if not any("\u1780" <= ch <= "\u17ff" for ch in result):
                    raise ValueError("vLLM response does not contain Khmer script")
                edited.append(replace(row, target_text=result))
        return edited
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Local vLLM post-editing failed: %s", exc)
        if settings.llm_fail_open if settings.llm_postedit_enabled else settings.vllm_fail_open:
            return rows
        raise RuntimeError("Offline vLLM post-editing failed") from exc
