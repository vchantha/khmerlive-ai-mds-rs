"""Optional offline Ollama/vLLM post-editing of timestamped English→Khmer segments.

The service is only called when explicitly enabled. Never send user text to
a public endpoint: the configured endpoint must be an internal Docker hostname.

Failure handling:
- Configuration errors (bad provider/endpoint) affect the whole job.
- A failure on one segment only reverts that segment (fail-open) instead of
  discarding every edit already made.
- A total wall-clock budget bounds how long post-editing may delay a job;
  segments left when it runs out keep their original translation.
"""
import json
import logging
import re
import time
from dataclasses import replace
from urllib.parse import urlsplit
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

# Reasoning models (e.g. Qwen3 thinking tags) may emit hidden chain-of-thought.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)

SYSTEM_PROMPT = (
    "You are a careful English-to-Khmer translation post-editor for video dubbing. "
    "Improve Khmer fluency without adding or deleting facts, numbers, names, or meaning. "
    "Keep the result concise and speakable. Return only the revised Khmer translation."
)


class PostEditError(ValueError):
    """A single segment could not be post-edited safely."""


def validate_local_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Offline LLM must use an internal HTTP endpoint")
    if parsed.hostname not in {"vllm", "ollama", "localhost", "127.0.0.1"}:
        raise ValueError("Offline LLM endpoint must be a trusted local service")
    if parsed.path.rstrip("/") not in {"", "/v1"}:
        raise ValueError("Offline LLM endpoint must end at /v1")
    return url.rstrip("/")


def strip_reasoning(text: str) -> str:
    """Remove <think>…</think> blocks, and any unterminated trailing <think>."""
    text = _THINK_BLOCK.sub("", text)
    text = _THINK_OPEN.sub("", text)
    return text.strip()


def _clean_output(content, draft: str) -> str:
    if not isinstance(content, str):
        raise PostEditError("LLM response content must be text")
    result = strip_reasoning(content)
    # Basic output guard; human evaluation remains necessary.
    if not result or len(result) > max(150, len(draft) * 3):
        raise PostEditError("LLM returned empty or excessively long output")
    if not any("ក" <= ch <= "៿" for ch in result):
        raise PostEditError("LLM response does not contain Khmer script")
    return result


def _resolve_config():
    if settings.llm_postedit_enabled:
        return dict(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout=float(settings.llm_timeout_seconds),
            max_tokens=settings.llm_max_tokens,
            fail_open=settings.llm_fail_open,
        )
    return dict(
        provider="vllm",
        base_url=settings.vllm_base_url,
        model=settings.vllm_model,
        timeout=float(settings.vllm_timeout_seconds),
        max_tokens=settings.vllm_max_tokens,
        fail_open=settings.vllm_fail_open,
    )


def _task(index, row, status, started, output=None, error=None):
    return {"index": index, "english": row.source_text, "draft": row.target_text, "output": output,
            "status": status, "seconds": round(time.monotonic() - started, 3) if started else None,
            "error": str(error)[:300] if error else None}


def postedit_rows(rows, source_lang: str, target_lang: str, report: list | None = None):
    """report: optional list that receives one dict per line (english, draft, output, status, seconds, error)."""
    """Return unchanged rows unless explicitly enabled for English→Khmer."""
    if not (settings.llm_postedit_enabled or settings.vllm_postedit_enabled) or source_lang != "en" or target_lang != "km":
        return rows
    cfg = _resolve_config()
    provider = cfg["provider"]
    try:
        if provider not in {"ollama", "vllm"}:
            raise ValueError("Unsupported offline LLM provider")
        endpoint = validate_local_endpoint(cfg["base_url"])
        if provider == "ollama" and urlsplit(endpoint).hostname not in {"ollama", "localhost", "127.0.0.1"}:
            raise ValueError("Ollama provider must use an Ollama endpoint")
    except ValueError as exc:
        logger.warning("Offline %s post-editing misconfigured: %s", provider, exc)
        if cfg["fail_open"]:
            return rows
        raise RuntimeError(f"Offline {provider} post-editing failed") from exc

    budget = float(getattr(settings, "llm_total_budget_seconds", 900.0))
    deadline = time.monotonic() + budget
    edited = list(rows)
    stats = {"edited": 0, "failed": 0, "skipped_budget": 0}

    concurrency = max(1, int(getattr(settings, "llm_concurrency", 1) or 1))
    if concurrency > 1:
        return _postedit_parallel(rows, cfg, endpoint, provider, budget, deadline, concurrency, report)

    with httpx.Client(timeout=cfg["timeout"], trust_env=False) as client:
        for index, row in enumerate(rows):
            if not row.target_text.strip():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                left = sum(1 for r in rows[index:] if r.target_text.strip())
                stats["skipped_budget"] = left
                if report is not None:
                    report.extend(_task(i, r, "skipped (time budget)", None) for i, r in enumerate(rows)
                                  if i >= index and r.target_text.strip())
                msg = f"Offline {provider} post-editing budget of {budget:.0f}s exhausted; {left} segments unedited"
                logger.warning(msg)
                if not cfg["fail_open"]:
                    raise RuntimeError(msg)
                break
            payload = _payload(cfg, row)
            started = time.monotonic()
            try:
                response = client.post(endpoint + "/chat/completions", json=payload,
                                       timeout=min(cfg["timeout"], remaining))
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                edited[index] = replace(row, target_text=_clean_output(content, row.target_text))
                stats["edited"] += 1
                if report is not None:
                    report.append(_task(index, row, "edited", started, edited[index].target_text))
            except httpx.ConnectError as exc:
                if report is not None:
                    report.append(_task(index, row, "failed (server unreachable)", started, error=exc))
                # The server is unreachable: stop rather than retry every segment.
                logger.warning("Offline %s endpoint unreachable: %s", provider, exc)
                if not cfg["fail_open"]:
                    raise RuntimeError(f"Offline {provider} post-editing failed") from exc
                stats["failed"] += 1
                break
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                logger.warning("Offline %s post-editing failed for segment %d: %s", provider, index, exc)
                if report is not None:
                    report.append(_task(index, row, "kept original (rejected output)" if isinstance(exc, PostEditError)
                                        else "kept original (request failed)", started, error=exc))
                if not cfg["fail_open"]:
                    raise RuntimeError(f"Offline {provider} post-editing failed") from exc
                stats["failed"] += 1  # keep this segment's original translation

    logger.info("Offline %s post-editing: %s", provider, stats)
    if stats["edited"] == 0:
        return rows
    return edited


def _payload(cfg, row) -> dict:
    return {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": cfg["max_tokens"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "english": row.source_text,
                "draft_khmer": row.target_text,
                "available_duration_ms": row.end_ms - row.start_ms,
            }, ensure_ascii=False)},
        ],
    }


def _postedit_parallel(rows, cfg, endpoint, provider, budget, deadline, concurrency, report=None):
    """Same per-segment requests and guards as the sequential path, N at a time.

    The server batches concurrent requests (Ollama: OLLAMA_NUM_PARALLEL; vLLM:
    continuous batching), so throughput rises without changing any prompt.
    """
    from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
    edited = list(rows)
    stats = {"edited": 0, "failed": 0, "skipped_budget": 0}
    todo = [i for i, r in enumerate(rows) if r.target_text.strip()]
    stop = False
    fatal: Exception | None = None

    started_at = {}

    def one(client, index):
        started_at[index] = time.monotonic()
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise TimeoutError("budget")
        r = client.post(endpoint + "/chat/completions", json=_payload(cfg, rows[index]),
                        timeout=min(cfg["timeout"], remaining))
        r.raise_for_status()
        return _clean_output(r.json()["choices"][0]["message"]["content"], rows[index].target_text)

    def note(index, status, output=None, error=None):
        if report is not None:
            report.append(_task(index, rows[index], status, started_at.get(index), output, error))

    with httpx.Client(timeout=cfg["timeout"], trust_env=False) as client, \
            ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = {}
        queue = iter(todo)
        while True:
            while not stop and len(pending) < concurrency:
                index = next(queue, None)
                if index is None:
                    break
                if deadline - time.monotonic() <= 1:
                    rest = [index, *queue]
                    stats["skipped_budget"] += len(rest)
                    for i in rest:
                        note(i, "skipped (time budget)")
                    stop = True
                    break
                pending[pool.submit(one, client, index)] = index
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                index = pending.pop(fut)
                try:
                    edited[index] = replace(rows[index], target_text=fut.result())
                    stats["edited"] += 1
                    note(index, "edited", edited[index].target_text)
                except TimeoutError:
                    stats["skipped_budget"] += 1
                    note(index, "skipped (time budget)")
                except httpx.ConnectError as exc:
                    note(index, "failed (server unreachable)", error=exc)
                    logger.warning("Offline %s endpoint unreachable: %s", provider, exc)
                    stats["failed"] += 1
                    stop = True
                    fatal = fatal or exc
                except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                    logger.warning("Offline %s post-editing failed for segment %d: %s", provider, index, exc)
                    note(index, "kept original (rejected output)" if isinstance(exc, PostEditError)
                         else "kept original (request failed)", error=exc)
                    stats["failed"] += 1
                    if not cfg["fail_open"]:
                        stop = True
                        fatal = fatal or exc
    if stats["skipped_budget"]:
        msg = f"Offline {provider} post-editing budget of {budget:.0f}s exhausted; {stats['skipped_budget']} segments unedited"
        logger.warning(msg)
        if not cfg["fail_open"]:
            raise RuntimeError(msg)
    if fatal is not None and not cfg["fail_open"]:
        raise RuntimeError(f"Offline {provider} post-editing failed") from fatal
    if report is not None:
        report.sort(key=lambda t: t["index"])
    logger.info("Offline %s post-editing (x%d parallel): %s", provider, concurrency, stats)
    return edited if stats["edited"] else rows


def preload_llm(attempts: int = 24, wait_seconds: float = 5.0, load_timeout: float = 300.0) -> bool:
    """Load the Ollama post-edit model into memory now (empty request; no text is generated).

    Retries while Ollama is still starting. Keep-alive follows the server's OLLAMA_KEEP_ALIVE.
    """
    if not settings.llm_postedit_enabled or settings.llm_provider != "ollama":
        return False
    try:
        endpoint = validate_local_endpoint(settings.llm_base_url)
    except ValueError as exc:
        logger.warning("LLM preload skipped: %s", exc)
        return False
    root = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
    for attempt in range(attempts):
        try:
            started = time.monotonic()
            with httpx.Client(timeout=load_timeout, trust_env=False) as client:
                client.post(root + "/api/generate", json={"model": settings.llm_model}).raise_for_status()
            logger.info("Preloaded LLM %s in %.1fs", settings.llm_model, time.monotonic() - started)
            return True
        except httpx.HTTPError as exc:
            if attempt == attempts - 1:
                logger.warning("Could not preload LLM %s: %s", settings.llm_model, exc)
                return False
            time.sleep(wait_seconds)
    return False


def unload_llm(timeout: float = 10.0) -> bool:
    """Ask Ollama to drop the post-edit model from (GPU) memory now. Next request reloads it."""
    if not settings.llm_postedit_enabled or settings.llm_provider != "ollama":
        return False
    try:
        endpoint = validate_local_endpoint(settings.llm_base_url)
        root = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            client.post(root + "/api/generate", json={"model": settings.llm_model, "keep_alive": 0}).raise_for_status()
        return True
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not unload the post-edit LLM: %s", exc)
        return False


def _model_matches(wanted: str, available: list[str]) -> bool:
    """Ollama lists 'name:tag'; an untagged request means ':latest'."""
    norm = lambda n: n if ":" in n else n + ":latest"
    return norm(wanted) in {norm(a) for a in available}


def llm_status(probe_timeout: float = 1.0) -> dict:
    """Report the optional post-editing LLM for the System health page.

    Probes the configured internal server (never a public host) with a short
    timeout and reports whether it answers and whether the model is present.
    status: off | ready | model_missing | offline | misconfigured
    """
    enabled = bool(getattr(settings, "llm_postedit_enabled", False) or getattr(settings, "vllm_postedit_enabled", False))
    if enabled:
        cfg = _resolve_config()
    else:
        # Not active: describe the provider a user would most likely enable.
        cfg = dict(provider=settings.llm_provider, base_url=settings.llm_base_url, model=settings.llm_model)
    provider, model = cfg["provider"], cfg["model"]
    out = {"enabled": enabled, "provider": provider, "model": model,
           "endpoint": cfg["base_url"], "server": "unknown", "model_available": None,
           "available_models": [], "status": "off", "detail": None,
           "processor": None, "gpu_percent": None}
    try:
        if provider not in {"ollama", "vllm"}:
            raise ValueError("Unsupported offline LLM provider")
        endpoint = validate_local_endpoint(cfg["base_url"])
    except ValueError as exc:
        out.update(status="misconfigured" if enabled else "off", detail=str(exc))
        return out
    try:
        with httpx.Client(timeout=probe_timeout, trust_env=False) as client:
            if provider == "ollama":
                root = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
                r = client.get(root + "/api/tags")
                r.raise_for_status()
                names = [m.get("name") or m.get("model") for m in r.json().get("models", [])]
            else:
                r = client.get(endpoint + "/models")
                r.raise_for_status()
                names = [m.get("id") for m in r.json().get("data", [])]
    except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        out.update(server="offline", detail=f"{provider} server not reachable")
        if enabled:
            out["status"] = "offline"
        logger.debug("LLM status probe failed: %s", exc)
        return out
    names = [n for n in names if isinstance(n, str)]
    available = _model_matches(model, names)
    out.update(server="online", available_models=names, model_available=available)
    if enabled:
        out["status"] = "ready" if available else "model_missing"
    out.update(_processor_status(provider, endpoint, model, probe_timeout) if available else {})
    return out


def _processor_status(provider: str, endpoint: str, model: str, probe_timeout: float) -> dict:
    """Where the model runs: processor = gpu | cpu | split | idle (not loaded) | None (unknown).

    Ollama's /api/ps reports size and size_vram per loaded model; vLLM only runs on GPU.
    Failures are non-fatal and leave processor unknown.
    """
    if provider == "vllm":
        return {"processor": "gpu", "gpu_percent": 100}
    root = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
    try:
        with httpx.Client(timeout=probe_timeout, trust_env=False) as client:
            r = client.get(root + "/api/ps")
            r.raise_for_status()
            loaded = r.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        logger.debug("LLM processor probe failed: %s", exc)
        return {}
    for m in loaded if isinstance(loaded, list) else []:
        if isinstance(m, dict) and _model_matches(model, [m.get("name") or m.get("model") or ""]):
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            if not isinstance(size, (int, float)) or size <= 0:
                return {}
            pct = max(0, min(100, round(100 * vram / size)))
            return {"processor": "gpu" if pct == 100 else "cpu" if pct == 0 else "split", "gpu_percent": pct}
    return {"processor": "idle", "gpu_percent": None}
