# KhmerLive AI — Deployment & Acceptance Tests

This is the required acceptance checklist for the new HTML5 preview and
bounded near-live English↔Khmer subtitle translation. **Passing unit/media
tests does not establish a perfect or production-ready translator.**

## 1. Safe Ubuntu 24.04 upgrade (preserves PostgreSQL and S3 volumes)

```bash
cd ~/khmerlive-ai-mds-rs
git pull origin main
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
docker compose run --rm --no-deps api pytest -q
python3 scripts/e2e-demo.py
```

The last command creates an actual 2-second H.264/AAC video, sends a multipart
upload through the browser-facing gateway, waits for the Celery job to complete,
gets a scoped preview grant and verifies HTTP 206 seekable MP4 bytes. This is a
**demo workflow E2E test**, not translation.

For fail diagnostics:

```bash
docker compose logs --tail=150 migrate api worker web minio minio-init
docker compose exec api python -c 'from app.config import settings; print(settings.model_mode)'
```

Never use `docker compose down -v` on an existing server.

## 2. Install and enable real local ASR + MT models

The source repository does not contain large model weights.

```bash
python3 -m venv .venv-models
source .venv-models/bin/activate
python -m pip install huggingface-hub==0.30.2
python scripts/download-models.py --output models
deactivate

docker compose -f compose.yaml -f compose.real.yaml config --quiet
docker compose -f compose.yaml -f compose.real.yaml up -d --build
docker compose -f compose.yaml -f compose.real.yaml run --rm --no-deps api pytest -q
docker compose -f compose.yaml -f compose.real.yaml ps -a
```

Requires sufficient available disk space, CPU RAM and preferably a dedicated
GPU for throughput. The provided `Dockerfile.real` currently uses a **CPU
PyTorch wheel**; do not claim GPU acceleration merely because the host has a
GPU. Review checkpoint and data licenses and test both translation directions.

### Verify English → Khmer from a REAL spoken MP4

```bash
python3 scripts/e2e-real.py --video /path/to/english-speech.mp4 --from-lang en
```

This rejects demo placeholders, verifies source ASR→target-language translation
produced non-empty Khmer Unicode SRT, confirms a completed MP4, and checks
HTTP 206 video range preview. The input should be a **short, clean,
human-understandable English clip** (<25 MB for the test script).

### Verify Khmer → English

```bash
python3 scripts/e2e-real.py --video /path/to/khmer-speech.mp4 --from-lang km
```

### Verify authorized HLS/MP4 URL near-live translation

In your private `.env`, explicitly allow only approved stream hostnames:

```env
STREAM_ALLOWED_HOSTS=stream.example.org
STREAM_URL_ALLOW_USERS=false
```

Replace with a real authorized public domain. Restart the worker/API and use:

```bash
docker compose -f compose.yaml -f compose.real.yaml up -d --build
python3 scripts/e2e-real.py --url 'https://stream.example.org/live/index.m3u8' --from-lang en --capture-seconds 30
```

Do not paste signed URLs containing credentials into shared logs or chats.
This path processes a **finite 15–120s capture**. The worker records segments
and persists translated text as each closed chunk is transcribed and translated.
This is *near-live*, with accuracy and latency dependent on the selected model
and hardware, **not** continuous low-latency speech-to-speech interpretation.

## 3. End-user Video Review expected behavior

A completed job in **Queue → Job Details** shows:
- Play/pause, full-screen, seek/scrub via HTML5 MP4.
- A dynamically refreshed short-lived playback grant; no API key in video URL.
- A selectable Khmer/English WebVTT subtitle track for real-subtitle jobs.
- Recognized speech and translated text, visible progressively during stream
  capture jobs when real inference finishes chunks.
- Download of H.264/AAC MP4 and translated SRT.
- Error message and Retry/Cancel state if a worker fails.

Browsers may differ in subtitle rendering and video codec support. Test Chrome,
Firefox and Safari as appropriate, especially Khmer fonts and UTF-8 subtitle
alignment. Existing old-format MP4s may require reprocessing.

## 4. Quality and release acceptance

Use `benchmarks/README.md` for monthly held-out data evaluation. Record
per-language CER/WER, translation chrF++, speaker review and critical errors,
clip alignment, time to first translated chunk, end-to-end latency, CPU/GPU
memory, and model revision. The repository provides code and test scripts but
**does not** have access to your private real-world clips, installed weights,
authorized live URL, hardware or OAuth provider credentials here.

**Known missing scope:** No Khmer voice synthesis/dubbing; no translated live
audio; no unlimited live stream; no production hardening of FFmpeg outbound
network isolation. The entire application cannot be certified as perfectly
working or translation-perfect until these explicit validation gates pass.
