# CPU-first offline Ollama post-editing for KhmerLive AI

This option preserves the existing vLLM backend and supplies a separate, opt-in
Ollama OpenAI-compatible backend for a 16 GB RAM development machine.
It runs after M2M100 and before Khmer TTS / subtitle muxing.

## Prerequisites

- Install Docker Compose. Prepare `.env` and ASR/MT/TTS models as documented for real mode.
- On a connected machine, pre-pull the pinned `OLLAMA_IMAGE` (or a compatible tested
  image) and model `OLLAMA_MODEL`. Verify model tags against your version before deploying.
- CPU-only inference with 16 GB RAM is slow; keep one Celery worker process and one
  concurrent Ollama request. Avoid running another large inference server simultaneously.

## Startup

```bash
docker compose -f compose.yaml -f compose.real.yaml -f compose.ollama.yaml config
docker compose -f compose.yaml -f compose.real.yaml -f compose.ollama.yaml up -d --build ollama
docker compose -f compose.yaml -f compose.real.yaml -f compose.ollama.yaml exec ollama ollama pull qwen3:4b-instruct
docker compose -f compose.yaml -f compose.real.yaml -f compose.ollama.yaml exec ollama ollama list
docker compose -f compose.yaml -f compose.real.yaml -f compose.ollama.yaml up -d --build
```

The `worker` overlay defaults to `LLM_POSTEDIT_ENABLED=false`. Only after testing
the model locally, set `LLM_POSTEDIT_ENABLED=true` in your `.env` and recreate
the worker. This prevents accidental inference outages during initial startup.

To verify the internal API from the running worker container:

```bash
docker compose -f compose.yaml -f compose.real.yaml -f compose.ollama.yaml exec worker \
  python -c 'import httpx; r=httpx.get("http://ollama:11434/v1/models",timeout=30); r.raise_for_status(); print(r.json())'
```

`LLM_FAIL_OPEN=true` falls back to the original M2M100 segments if any segment
request fails. Use `false` for strictly reproducible failure-aware experiments.

## Tests

```bash
docker compose -f compose.yaml -f compose.real.yaml -f compose.ollama.yaml \
  run --rm --no-deps worker python -m pytest -q tests/test_llm_postedit.py
```

The Docker command above assumes the backend working directory is `/app` and
tests are included in the worker image. If excluded by Dockerfile, run the tests
from the backend source in a Python environment with requirements installed.

For end-to-end offline validation, disconnect outbound Internet after preloading
the images and weights, then process a short rights-cleared English MP4 and inspect
the Khmer output with a native speaker. No model weights or runtime are automatically
downloaded by these source-code changes.

## Research

Compare M2M100, Qwen prompting and QLoRA post-editing on the same video-level split.
Store baseline and edited texts, model version, prompts and runtime measurements.
The adapter is **post-editing inference**, not LoRA training. Training requires a
separate GPU-capable experiment environment and human-reviewed Khmer references.
