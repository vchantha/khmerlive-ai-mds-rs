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
import hashlib
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

# "translate" (default): the LLM translates the English itself, using the machine draft only as a
# possibly-wrong hint, neighbouring lines for context and the glossary for required terms.
TRANSLATE_PROMPT = (
    "You translate English video speech into natural spoken Khmer for dubbing, the way a native "
    "Khmer speaker would say it aloud (casual when the English is casual). Translate the meaning of "
    "the English line exactly and keep every noun, name and number. The previous and next lines are "
    "context only; do not translate them. The machine draft may contain wrong words: never copy a "
    "word that does not match the English. If required_terms are given you must use those Khmer "
    "words. Keep it short enough to say in the available time. Reply with only the Khmer line."
)

# "polish" (previous behaviour): minimal fluency edits of the machine draft.
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


# Khmer block (U+1780–U+17FF) and Khmer Symbols (U+19E0–U+19FF).
def _is_khmer(ch: str) -> bool:
    return "\u1780" <= ch <= "\u17ff" or "\u19e0" <= ch <= "\u19ff"

# Dependent vowels, signs and the coeng (U+17B6–U+17D3, U+17DD) cannot start a cluster.
def _is_khmer_dependent(ch: str) -> bool:
    return "\u17b6" <= ch <= "\u17d3" or ch == "\u17dd"

_KHMER_DIGITS = str.maketrans("០១២៣៤៥៦៧៨៩", "0123456789")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WRAPPER_LABEL = re.compile(r"^(?:khmer|translation|revised(?: khmer)?(?: translation)?|answer|ខ្មែរ|ការបកប្រែ)\s*[:：]\s*",
                            re.IGNORECASE)
_QUOTES = "\"'“”‘’«»`"


def numbers_in(text: str) -> set[str]:
    """Numbers written with Arabic or Khmer digits, normalized ("1,000" and "១០០០" → "1000")."""
    found = set()
    for n in _NUMBER.findall((text or "").translate(_KHMER_DIGITS)):
        # "1,000" groups thousands; "2.5" keeps its decimal point.
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", n):
            n = n.replace(",", "")
        found.add(n.rstrip(".,"))
    return found


def _unwrap(text: str) -> str:
    """Drop formatting a chat model may wrap the line in: code fences, a label, quotes."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```") and len(text) >= 6:
        text = text[3:-3].strip()
        if "\n" in text and not any(_is_khmer(c) for c in text.split("\n", 1)[0]):
            text = text.split("\n", 1)[1].strip()   # ```khmer language tag line
    text = _WRAPPER_LABEL.sub("", text).strip()
    if len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    return text


def validate_khmer_line(result: str, source: str, draft: str) -> None:
    """Reject outputs that are malformed or that change facts the draft preserved.

    These are safety guards, not a quality score: a line that passes still needs
    human review (adequacy, fluency), and Khmer script alone proves nothing.
    """
    if not result:
        raise PostEditError("LLM returned an empty line")
    if "\n" in result:
        raise PostEditError("LLM returned several lines instead of one")
    if "\ufffd" in result or any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 for c in result):
        raise PostEditError("LLM output contains invalid or control characters")
    khmer = sum(1 for c in result if _is_khmer(c))
    latin = sum(1 for c in result if c.isascii() and c.isalpha())
    if khmer == 0:
        raise PostEditError("LLM response does not contain Khmer script")
    if latin > khmer:
        raise PostEditError("LLM response is mostly Latin script, not Khmer")
    if _is_khmer_dependent(result[0]):
        raise PostEditError("LLM output starts with a Khmer dependent sign (malformed text)")
    if len(result) > max(150, len(draft) * 3):
        raise PostEditError("LLM returned excessively long output")
    if len(draft) >= 20 and len(result) < len(draft) * 0.35:
        raise PostEditError("LLM output is much shorter than the draft (likely dropped content)")
    if source and result.strip().lower() == source.strip().lower():
        raise PostEditError("LLM echoed the English source")
    # Numbers: never drop a number the draft kept, never invent one.
    src, drf, out = numbers_in(source), numbers_in(draft), numbers_in(result)
    dropped = sorted((src & drf) - out)
    if dropped:
        raise PostEditError("LLM dropped or changed number(s): " + ", ".join(dropped))
    invented = sorted(out - src - drf)
    if invented:
        raise PostEditError("LLM introduced number(s) not in the source: " + ", ".join(invented))


def _clean_output(content, draft: str, source: str = "") -> str:
    if not isinstance(content, str):
        raise PostEditError("LLM response content must be text")
    result = _unwrap(strip_reasoning(content))
    validate_khmer_line(result, source, draft)
    return result


def prompt_version(mode: str | None = None) -> str:
    """Short hash of the prompt in use, stored with results so experiments are reproducible."""
    mode = mode or _mode()
    text = TRANSLATE_PROMPT if mode == "translate" else SYSTEM_PROMPT
    return f"{mode}-{hashlib.sha256(text.encode()).hexdigest()[:10]}"


def _resolve_config():
    if settings.llm_postedit_enabled:
        return dict(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout=float(settings.llm_timeout_seconds),
            max_tokens=settings.llm_max_tokens,
            fail_open=settings.llm_fail_open,
            retries=max(0, int(getattr(settings, "llm_max_retries", 0) or 0)),
        )
    return dict(
        provider="vllm",
        base_url=settings.vllm_base_url,
        model=settings.vllm_model,
        timeout=float(settings.vllm_timeout_seconds),
        max_tokens=settings.vllm_max_tokens,
        fail_open=settings.vllm_fail_open,
        retries=max(0, int(getattr(settings, "llm_max_retries", 0) or 0)),
    )


def _task(index, row, status, started, output=None, error=None):
    return {"index": index, "english": row.source_text, "draft": row.target_text, "output": output,
            "status": status, "seconds": round(time.monotonic() - started, 3) if started else None,
            "error": str(error)[:300] if error else None}


def postedit_rows(rows, source_lang: str, target_lang: str, report: list | None = None, terms: list | None = None):
    """Return unchanged rows unless explicitly enabled for English→Khmer.

    report: optional list that receives one dict per line (english, draft, output, status, seconds, error).
    terms: glossary terms (app.glossary.Term) the LLM must use where the English contains them.
    """
    if not (settings.llm_postedit_enabled or settings.vllm_postedit_enabled) or source_lang != "en" or target_lang != "km":
        return rows
    cfg = _resolve_config()
    provider = cfg["provider"]
    if provider == "none":
        return rows   # LLM_PROVIDER=none: keep the machine translation, no network call.
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
        return _postedit_parallel(rows, cfg, endpoint, provider, budget, deadline, concurrency, report, terms)

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
            started = time.monotonic()
            try:
                text, miss = _ask(client, endpoint, cfg, rows, index, terms, min(cfg["timeout"], remaining), deadline)
                edited[index] = replace(row, target_text=text)
                stats["edited"] += 1
                if report is not None:
                    report.append(_task(index, row, _status(row, text, miss), started, text))
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


def _mode() -> str:
    return getattr(settings, "llm_mode", "polish") or "polish"


def _payload(cfg, row, rows=None, index=None, terms=None, insist=None) -> dict:
    if _mode() == "translate":
        rows = rows or [row]
        i = index if index is not None else 0
        user = {"english": row.source_text,
                "previous_line": rows[i - 1].source_text if i > 0 else "",
                "next_line": rows[i + 1].source_text if i + 1 < len(rows) else "",
                "machine_draft_may_be_wrong": row.target_text,
                "available_seconds": round((row.end_ms - row.start_ms) / 1000, 1)}
        if terms:
            user["required_terms"] = {t.source: t.target for t in terms}
        messages = [{"role": "system", "content": TRANSLATE_PROMPT},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]
        if insist:
            messages.append({"role": "user", "content": "Your answer must contain these Khmer words: "
                             + ", ".join(f"{t.target} ({t.source})" for t in insist) + ". Reply with only the Khmer line."})
    else:
        user = {"english": row.source_text, "draft_khmer": row.target_text,
                "available_duration_ms": row.end_ms - row.start_ms}
        system = SYSTEM_PROMPT
        if terms:
            user["required_terms"] = {t.source: t.target for t in terms}
            system += (" The draft may mistranslate the English words listed in required_terms; "
                       "replace them with the given Khmer words.")
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]
    if insist and _mode() != "translate":
        messages.append({"role": "user", "content": "Your answer must contain these Khmer words: "
                         + ", ".join(f"{t.target} ({t.source})" for t in insist) + ". Reply with only the Khmer line."})
    return {"model": cfg["model"], "temperature": 0, "max_tokens": cfg["max_tokens"], "messages": messages}


def _status(row, text, miss) -> str:
    base = "unchanged" if text == row.target_text else "edited"
    return base if not miss else f"{base} (missing term: " + ", ".join(t.source for t in miss) + ")"


_RETRY_STATUS = {429, 500, 502, 503, 504}


def _complete(client, endpoint, cfg, payload, timeout, deadline=None) -> str:
    """POST one chat completion, retrying transient failures (timeouts, 429, 5xx).

    Connection refusals are not retried (the caller stops: the server is down), nor are
    rejected outputs (temperature 0 would return the same text). Retries never exceed
    the job's post-editing deadline.
    """
    attempts = 1 + cfg.get("retries", 0)
    for attempt in range(attempts):
        try:
            r = client.post(endpoint + "/chat/completions", json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            transient = isinstance(exc, httpx.TimeoutException) or exc.response.status_code in _RETRY_STATUS
            left = None if deadline is None else deadline - time.monotonic()
            if not transient or attempt == attempts - 1 or (left is not None and left <= 1):
                raise
            if left is not None:
                timeout = min(timeout, left)
            logger.info("Retrying LLM request after %s (attempt %d/%d)", type(exc).__name__, attempt + 2, attempts)
            time.sleep(min(0.5 * (attempt + 1), 2.0))
    raise RuntimeError("unreachable")


def _ask(client, endpoint, cfg, rows, index, terms, timeout, deadline=None):
    """One line: request, guard, and (glossary) one retry if a required term is missing.

    Returns (text, missing_terms)."""
    from app.glossary import terms_for, missing_terms
    row = rows[index]
    required = terms_for(row.source_text, terms) if terms else []
    content = _complete(client, endpoint, cfg, _payload(cfg, row, rows, index, required), timeout, deadline)
    text = _clean_output(content, row.target_text, row.source_text)
    miss = missing_terms(text, required)
    if miss:
        content = _complete(client, endpoint, cfg, _payload(cfg, row, rows, index, required, insist=miss), timeout, deadline)
        retry = _clean_output(content, row.target_text, row.source_text)
        if len(missing_terms(retry, required)) < len(miss):
            text, miss = retry, missing_terms(retry, required)
    return text, miss


def _postedit_parallel(rows, cfg, endpoint, provider, budget, deadline, concurrency, report=None, terms=None):
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
        return _ask(client, endpoint, cfg, rows, index, terms, min(cfg["timeout"], remaining), deadline)

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
                    text, miss = fut.result()
                    edited[index] = replace(rows[index], target_text=text)
                    stats["edited"] += 1
                    note(index, _status(rows[index], text, miss), text)
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
            # Ollama frees VRAM just after replying; wait until it no longer lists the model.
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                loaded = client.get(root + "/api/ps").json().get("models", [])
                if not any(_model_matches(settings.llm_model, [m.get("name") or m.get("model") or ""]) for m in loaded):
                    break
                time.sleep(0.25)
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
           "processor": None, "gpu_percent": None, "prompt_version": prompt_version(),
           "mode": _mode()}
    if provider == "none":
        out.update(status="off", server="not used", detail="LLM_PROVIDER=none: machine translation is used unchanged")
        return out
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
        if not available:
            out["detail"] = (f"Model '{model}' is not on the {provider} server. Weights are never downloaded "
                             "automatically offline; provision them first (see docs/OFFLINE_OLLAMA.md / OFFLINE_VLLM.md).")
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


SMOKE_SOURCE = "The course has 12 lessons."
SMOKE_DRAFT = "វគ្គសិក្សានេះមាន 12 មេរៀន។"


def llm_smoke_test(timeout: float | None = None) -> dict:
    """Readiness beyond "the server answers": run one real post-edit through the same guards.

    Returns ok, seconds, output, error, provider, model and prompt_version. Used by
    `python -m app.llm_postedit --smoke` and the admin smoke-test endpoint.
    """
    status = llm_status()
    out = {"ok": False, "provider": status["provider"], "model": status["model"],
           "prompt_version": status["prompt_version"], "status": status["status"],
           "seconds": None, "output": None, "error": None}
    if status["status"] != "ready":
        out["error"] = status.get("detail") or f"LLM is not ready (status: {status['status']})"
        return out
    cfg = _resolve_config()
    endpoint = validate_local_endpoint(cfg["base_url"])
    timeout = float(timeout or cfg["timeout"])

    class _Row:
        start_ms, end_ms, source_text, target_text = 0, 2500, SMOKE_SOURCE, SMOKE_DRAFT
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            text, _ = _ask(client, endpoint, cfg, [_Row], 0, None, timeout)
        out.update(ok=True, output=text)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
    out["seconds"] = round(time.monotonic() - started, 3)
    return out


if __name__ == "__main__":   # python -m app.llm_postedit [--smoke]
    import sys
    result = llm_smoke_test() if "--smoke" in sys.argv else llm_status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("ok", result.get("status") == "ready") else 1)
