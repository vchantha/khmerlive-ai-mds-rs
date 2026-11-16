# KhmerLive AI — Docker Compose Research MVP

## 🚀 Deploy (quick guide)

One script deploys everything. It detects an NVIDIA GPU and picks the right
setup, and it remembers that choice, so later plain `docker compose ...` commands work.

### 1. Requirements

| | CPU-only | With NVIDIA GPU |
|---|---|---|
| OS | Ubuntu 22.04/24.04/26.04 (any Linux with Docker) | same |
| Docker | Docker Engine + Compose v2 | same + **NVIDIA driver** + **NVIDIA Container Toolkit** |
| RAM | 8 GB min, 16 GB+ recommended | same |
| Disk | ~15 GB (images + models) | ~25 GB (CUDA image is ~10 GB) |
| GPU | — | 4 GB VRAM works (tested: Quadro T1000); 8 GB+ is faster |

### 2. One-time setup

```bash
git clone <this repo> && cd khmerlive-ai-mds-rs
bash scripts/init-env.sh                 # creates .env with random secrets (never commit it)
pip install --user huggingface_hub       # needed by the download script
python3 scripts/download-models.py       # speech, translation, Khmer voice models → ./models
```

Optional AI polishing of Khmer translations (local LLM via Ollama): set
`LLM_POSTEDIT_ENABLED=true` in `.env`. The deploy script pulls the model.

**GPU only, one time.** Let Docker use the GPU:

```bash
nvidia-smi                                # must list your GPU (install the NVIDIA driver first)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
docker info | grep -i runtimes            # must show "nvidia"
```

### 3. Deploy

```bash
./scripts/deploy.sh          # auto: GPU if Docker can use it, otherwise CPU
./scripts/deploy.sh --cpu    # force CPU-only
./scripts/deploy.sh --gpu    # force GPU
./scripts/deploy.sh --demo   # no models; placeholder output (UI test only)
```

The script:
1. picks the Compose files and saves them as `COMPOSE_FILE` in `.env`;
2. builds and starts everything;
3. converts the translation model to the fast engine (one time);
4. pulls the LLM;
5. waits until the API is ready.

Open **http://localhost:8080** and sign in with `API_KEY` from `.env`.

### 4. Check it works

```bash
docker compose ps                                 # all services Up / healthy
docker compose logs --tail=50 worker              # "Worker process: N CPU threads per job; devices asr=… mt=… tts=…"
docker compose exec ollama ollama ps              # GPU: PROCESSOR = 100% GPU
```

Every finished job records how long each stage took. You can see this under `timings` in
`GET /api/jobs/<id>`, or in the worker log line `Job … finished in …s`.

### 5. Everyday commands

| Task | Command |
|---|---|
| Update after `git pull` | `./scripts/deploy.sh` (same mode as before) |
| Restart the worker | `docker compose restart worker` |
| Follow logs | `docker compose logs -f worker api` |
| Stop / start | `docker compose stop` / `docker compose start` |
| Switch CPU ↔ GPU | `./scripts/deploy.sh --cpu` or `--gpu` |
| Re-convert translation model | `FORCE=1 ./scripts/convert-mt-ct2.sh && docker compose restart worker` |

### Performance: what runs where

Measured on one 9.3-minute English video, Quadro T1000 (4 GB) + 12-core CPU:

| Stage | CPU-only | GPU deployment | How |
|---|---|---|---|
| Speech recognition | 51.5 s (Whisper small) | **25 s** (Whisper **large-v3-turbo**) | GPU `int8_float16`. Turbo makes **41% fewer word errors** (LibriSpeech: 7.48% → 4.43% WER) |
| Translation (M2M100) | 66 s (Transformers) | **~19 s** | CTranslate2 int8 on CPU, used automatically in both modes |
| Khmer voice (MMS VITS) | 33 s / 20 lines | **3.1 s / 20 lines** | GPU |
| LLM polishing (qwen3 4B) | ~10–15 s / line | **~2.4 s / line** (≈4.8 s each, 2 at once) | Ollama on GPU; now the slowest stage |

Whole job, 6.9-minute video: **19.8 min (old CPU pipeline) → 5.3 min (GPU)**, faster than real time.

CTranslate2 and Transformers use slightly different decoding, so CTranslate2 phrases some
translations differently (mean character similarity about 0.74). Neither version is clearly
better. To get the old engine back, set `MT_ENGINE=transformers` in `.env`.

### Tuning (`.env`, then `./scripts/deploy.sh`)

| Setting | Default | When to change |
|---|---|---|
| `WORKER_CONCURRENCY` | `1` | Videos processed at the same time. CPU-only: about 1 per 4 cores and 4 GB RAM. CPU threads are split between them automatically. Keep `1` on a 4 GB GPU |
| `CPU_THREADS` | `0` (auto) | Threads per video; auto = cores ÷ concurrency |
| `MT_ENGINE` | `auto` | `transformers` = original engine (slower) |
| `ASR_DEVICE` / `TTS_DEVICE` / `MT_DEVICE` | GPU mode: `cuda`/`cuda`/`cpu` | GPU with 8 GB+: `MT_DEVICE=cuda` |
| `ASR_RELEASE_AFTER_USE` | GPU mode: `true` | Frees Whisper's VRAM after each use (~1 s reload). `false` on 8 GB+ |
| `LLM_CONCURRENCY` + `OLLAMA_NUM_PARALLEL` | GPU: `2` | Parallel LLM lines. Raise both together on bigger GPUs |
| `OLLAMA_MODEL` | `qwen3:4b-instruct` | Smaller (`qwen3:1.7b`) if `ollama ps` shows a CPU/GPU split, or for faster polishing (check Khmer quality) |
| `LLM_PRELOAD_ON_START` | `true` | The worker loads the LLM into memory at startup, so the first job doesn't wait for it (a cold load took 46 s). `OLLAMA_KEEP_ALIVE=-1` keeps it loaded even when idle |
| `WORKER_MAX_TASKS_PER_CHILD` | GPU: `1` | Fresh worker process per job so all GPU memory is freed between jobs (models reload in a few seconds). `0` = keep the process |

### Speech recognition model

| Deployment | Model | Word error rate* | Notes |
|---|---|---|---|
| GPU | **Whisper large-v3-turbo** (default) | **4.43%** | ~1.1 GB VRAM. On a 4 GB GPU the LLM is unloaded during speech recognition and reloaded for post-editing (adds ~3 s per job) |
| CPU-only | Whisper small (default) | 7.48% | Turbo also works on CPU (`WHISPER_MODEL_PATH=/models/asr-large-v3-turbo`), about 4× slower |

\*Measured on 73 LibriSpeech clean utterances with human reference transcripts.
`./scripts/deploy.sh --gpu` downloads turbo automatically (1.6 GB, once). To use small on the GPU, set
`GPU_WHISPER_MODEL_PATH=/models/asr`.

We also tested asking the LLM (qwen3:4b) to correct the transcripts. It made them **worse**
(4.43% → 5.30% WER; it also "corrected" words that were already right), so it isn't part of the pipeline.

### Glossary: fix words the model keeps getting wrong

Open **Glossary** (Administration) and add terms such as *elephant → ដំរី*. When an English line
contains a term (whole word, plurals too: *elephants*), the LLM post-editor must use your Khmer word. If its
answer doesn't contain the word, it is asked once more. Lines that still miss it show
`edited (missing term: …)` in the job's **Pipeline log → LLM tasks**. This works right away, with no
training. It needs LLM post-editing enabled (`LLM_POSTEDIT_ENABLED=true`) and applies to new jobs.

Tested on "Me at the zoo": without the glossary, M2M100 turned *elephants* into អ៊ីនធឺណិត (*internet*) and
the LLM kept it; with *elephant → ដំរី* the line says ដំរី. The glossary can only fix words the speech
recognizer heard correctly. If the English line itself is wrong (e.g. *trunks* heard as *fronts*), fix it in
**Review translation**.

`LLM_MODE` sets how the LLM works: `polish` (default) makes small edits to the machine draft;
`translate` has the LLM translate the English itself, using the draft only as a hint and the neighbouring
lines as context. On the zoo test, `translate` gave the better first line and a worse third line, so
`polish` stays the default until more reviewed lines show otherwise.

### Improving translation with your own corrections (fine-tuning)

The translation model (M2M100) makes word-level mistakes, for example "elephants" → "internet".
You can teach it your content and style:

1. **Review.** Open a finished job and expand **Review translation**. For each line, either fix the
   Khmer or click **Correct** if it's already right, then **Save** (Ctrl+Enter). The play button on
   each line jumps the video there. Only lines you saved become training data.
2. **Track progress.** The **Datasets** page shows how many lines are verified. Collect **300+ lines**
   from several videos before training (the script refuses with fewer than 100).
3. **Train.** On the server, run:
   ```bash
   ./scripts/finetune-mt.sh              # train, evaluate, deploy only if better
   ./scripts/finetune-mt.sh --no-deploy  # train and evaluate only
   ./scripts/finetune-mt.sh --rollback   # back to the original model
   ```
   The script trains a LoRA adapter on the GPU (it pauses the worker meanwhile; queued jobs wait). It then
   scores the old and new models on **videos held out from training** (chrF++) and switches
   `MT_CT2_PATH` only if the new model scores at least 1 point higher. Each run's report, with
   example translations, is saved at `models/mt-ft-<date>/report.json`.

Notes: the first run needs Internet once (it installs the PEFT library into the training container).
Jobs processed before this feature can't be reviewed; run the video again to review it. Fix the
translation of what was said; if the English line itself is wrong (a speech-recognition error), translate
what the speaker actually said.

### Khmer voice (dubbing) behaviour

Each Khmer line is spoken at **natural speed and pitch**, starting at its subtitle time.
It is never slowed down to fill a gap. A line longer than the pause before the next line is
sped up, first through the voice model's own speaking rate (up to 1.5×), then with a
pitch-preserving tempo change (up to 2× in total). The rare line that still doesn't fit is
trimmed with a fade, and the worker log reports how each line was placed (`Khmer dub: …`).
Every line is normalised to the same loudness and gets short fades, so there are no clicks.

### Troubleshooting

| Symptom | Fix |
|---|---|
| Deploy says "NVIDIA GPU found but Docker can't use it" | Install the NVIDIA Container Toolkit (step 2), then `./scripts/deploy.sh --gpu` |
| `CUDA failed with error out of memory` in worker logs | Keep `MT_DEVICE=cpu` and `ASR_RELEASE_AFTER_USE=true`; check `nvidia-smi`; use a smaller `OLLAMA_MODEL` |
| `ollama ps` shows e.g. `30%/70% CPU/GPU` | Model doesn't fit in VRAM: smaller model or lower `OLLAMA_CONTEXT_LENGTH` |
| Job stuck "processing" after a restart | Recovered automatically when the worker starts (marked *Interrupted*, press **Retry**) |
| Cancel | Stops the job immediately (the running step is terminated). If it shows "Cancelling…", click **Stop now** |
| Slow on CPU-only | Expected: GPU is 4–10× faster for speech and voice. Make sure `models/mt-ct2` exists (fast translation) |

---

## Khmer voice dubbing (new)

English→Khmer real-model jobs can now replace English speech with an offline
synthetic Khmer voice and include Khmer subtitles. Read
[Khmer dubbing deployment and license requirements](docs/KHMER_DUBBING.md).
The Khmer MMS TTS checkpoint is **non-commercial CC-BY-NC-4.0** and model
weights must be downloaded separately. Existing completed videos are not
retroactively dubbed. Default Docker Compose remains **demo**; use
`docker compose -f compose.yaml -f compose.real.yaml up -d --build`.
No end-to-end Khmer speech synthesis on the user's machine has been verified.

**Research:** Uncertainty-Aware Adaptive Speech Segmentation for Low-Latency Offline English–Khmer Simultaneous Translation. [Notion roadmap](https://app.notion.com/p/41931200c90381c9bd02d240f29d9392).

> **Important: Infrastructure DEMO, not a working Khmer translator.** ASR and MT return explicit demo placeholders, and FFmpeg re-muxes the original audio/video unchanged. Khmer AI models, TTS, adaptive streaming and measured accuracy are not yet implemented. Never represent the exported video as dubbed or translated. This repo is a reproducible *Phase 0–1 service foundation*, not a completed research result.

## Services
- React + Vite interface (Nginx on `http://localhost:8080`)
- FastAPI HTTP API (internal port 8000)
- Celery worker with Redis queue
- PostgreSQL 16 (durable media/job records, Alembic migration)
- PGSTY SILO, a maintained MinIO-compatible S3 server (durable object storage; service retains the `minio` hostname for app compatibility)
- FFmpeg worker pipeline (audio extraction and MP4 passthrough)

## Fix for MinIO / Quay 401 (Nov 2026)
The upstream historical `quay.io/minio/*` images now return 401 to anonymous pulls. This Compose stack uses `docker.io/pgsty/silo:RELEASE.2026-11-09T00-00-00Z`, a community-maintained MinIO-compatible fork. A fresh install should run `docker compose pull` before `up`. Existing S3 data migration must be validated and backed up before upgrading an existing volume. Image pull and runtime compatibility still need verification on your host.

## Upload size / HTTP 413 troubleshooting

The Nginx gateway accepts up to 2 GiB request bodies; FastAPI separately enforces `MAX_UPLOAD_MB` (default **1024 MiB** on fresh installations). Existing `.env` files are **not automatically updated** when you pull a new commit.

If uploading a file larger than your configured limit, edit the existing `.env` (never commit it) to include:

```env
MAX_UPLOAD_MB=1024
```

Then rebuild the gateway and restart services so both limits apply:

```bash
git pull origin main
docker compose up -d --build --force-recreate web api worker
docker compose exec web nginx -T 2>&1 | grep client_max_body_size
docker compose exec api python -c 'from app.config import settings; print("MAX_UPLOAD_MB =", settings.max_upload_mb)'
```

If a 413 persists, check `docker compose logs --tail=100 web api` and any **external ingress/reverse proxy** which may have a smaller request body limit. Large uploads need adequate disk space for multipart spooling and S3 storage. Demo mode does **not** perform real translation.

## Ubuntu 24.04 quick start
Install Docker Engine and Compose v2 from official Docker packages. Run:

```bash
bash scripts/init-env.sh
# This generates coherent random PostgreSQL/MinIO/API secrets. Do not commit .env.
docker compose config --quiet
docker compose pull db redis minio minio-init
# CI and Dockerfile build may still require an internet connection.
docker compose up --build -d
docker compose ps
bash scripts/smoke.sh
```

Open `http://localhost:8080`, paste `API_KEY` from `.env`, upload an MP4 with audio, choose language direction, submit, refresh and download a **pass-through video**. No real translation will occur.

## Dashboard UI / queue monitoring

The redesigned light enterprise dashboard interface is served on `http://localhost:8080`. It provides:
- Dashboard counters computed from **actual PostgreSQL jobs**, with no sample metrics.
- MP4 upload drag-and-drop, source-language selector, API-key session dialog, and real upload progress.
- Live queue with server-side search, status filtering, pagination and 8-second auto-refresh.
- Persisted worker progress checkpoints (5/25/45/65/85/100%), stage labels, job errors and download.
- Job detail panel, completed results, and real-time API, PostgreSQL, Redis, S3 and worker status checks (worker ping can be unknown).
- Responsive layout. Demo mode remains explicit; video preview is deliberately a placeholder and no translation results are fabricated.

**Upgrade an existing deployment without deleting persistent data:**

```bash
git pull origin main
docker compose up -d --build
docker compose ps -a
curl -fsS http://localhost:8080/api/health/ready
```

The `migrate` service applies Alembic revision `0002_job_progress` to existing PostgreSQL records, setting previously completed jobs to 100%. Do **not** run `docker compose down -v`. Access the UI on port 8080 (or configured `WEB_PORT`) and set the API key from your local `.env`.

```bash
docker compose run --rm --no-deps api pytest -q
docker compose logs --tail=100 api worker web
```

## Streaming video by URL (HTTP(S) / HLS)

The redesigned **Start a new job** panel supports two inputs: **Upload MP4** and **Stream by URL**. The URL mode accepts approved public HTTP(S) MP4 and HLS `.m3u8` streams, captures a short 5–120 second excerpt (UI presets: 15, 30, 60, 120), saves the MP4 to object storage and adds a processing job to the **real PostgreSQL queue**. The generated demo output keeps the original audio; it is **not live translation**.

URL mode is **disabled by default**. In your existing private server `.env`, set an explicit comma-separated allowlist of public domain names you control or are authorized to ingest, for example:

```env
STREAM_ALLOWED_HOSTS=media.example.org,cdn.example.org
```

Replace example domains with your actual stream hostnames. This list is an authorization boundary, **not** a complete network sandbox: FFmpeg may follow stream manifests and redirects that reference other destinations, so enforce outbound firewall/egress ACLs and deny private networks at the host/network layer. Do not allow untrusted public users to submit URLs. URL input rejects non-HTTP(S), credentials in URL authority, unusual ports, unlisted hosts and hosts with private DNS answers. Only ingest streams that you are permitted to access.

Restart after updating `.env` and pulling the newest code:

```bash
git pull origin main
docker compose up -d --build
docker compose exec migrate alembic current || true
docker compose logs --tail=80 api worker
```

The automatic migration `0004_stream_url` adds the source URL and capture settings to PostgreSQL, and captures use the existing S3-compatible storage. Stream URLs may contain secrets as query parameters: avoid authenticated/signed URLs in this MVP because the URL is stored in PostgreSQL. RTSP, RTMP, YouTube **webpage links**, DRM-protected services and continuous WebRTC/RTMP translation are **not supported**. Streaming input needs access to the source over your network; a fully air-gapped deployment can only access streams hosted on its permitted local network, which would require explicitly reviewed network policy.


## Real English ↔ Khmer subtitle translation (optional, model weights required)

The service is still configured in `demo` mode by default for safe upgrades.
A separate Compose override (`compose.real.yaml`) adds **Whisper ASR + M2M100 translation**,
outputs UTF-8 translated SRT files and an MP4 containing a selectable subtitle track.
**Audio remains unchanged. Khmer voice dubbing, alignment, production-grade streaming ASR and model-quality validation are NOT implemented.**

1. On a **network-connected staging machine** with sufficient disk/RAM, install:
   `python3 -m pip install 'huggingface-hub==0.30.2'`.
2. From repository root run `python3 scripts/download-models.py --output models`.
   This resolves model repositories to immutable revisions, writes model hashes and downloads
   `Systran/faster-whisper-small` and `facebook/m2m100_418M` locally.
   **Review exact model licenses, upstream terms, provenance and the model revisions before any business use.**
   Evaluate Khmer and English accuracy independently; do not assume a usable result from this unbenchmarked model pair.
3. Check `models/asr/model.bin`, `models/mt/config.json` and `models/manifest.lock.json` exist. Transfer the entire model bundle securely to the target computer. Do not commit weights or `.env` into Git.
4. Enable local inference with:

```bash
docker compose -f compose.yaml -f compose.real.yaml up -d --build
docker compose -f compose.yaml -f compose.real.yaml ps -a
docker compose -f compose.yaml -f compose.real.yaml run --rm --no-deps api pytest -q
```

5. Log into the UI, upload a short English MP4 containing **clearly spoken audio**, wait for Completed and download the MP4 and SRT. Select **English** as spoken language. Subtitle tracks are selectable by the player; they are **not burned-in captions**.
   For a local WAV inference test, use `scripts/selftest-real.py` in a worker with the WAV mounted inside its filesystem (audio path, models and dependencies must exist).
6. Benchmark word error rate, chrF++, Khmer native-speaker acceptability, timing and offline network behavior before calling this feature accurate or release-ready.

**Safety:** No internet model download occurs inside the inference workers, but building Docker images and staging model files require network access unless separately packaged. Neither GPU inference nor real ASR/MT has been validated on the user's Ubuntu hardware. Model download alone does not prove correct translation.

## Users, Google / Facebook / GitHub social login, and responsive navigation

The **Users & Social** page supports optional account creation by Google, Facebook or GitHub OAuth, linking a second provider to an existing account, and sign-out. Signed-in users see only their own jobs, while the legacy shared API key is reserved for trusted local administrator use. On the same page an administrator using the API key can view the registered user directory.

**All social providers default to disabled** until OAuth applications, client IDs/secrets and callback URLs have been created with the external identity providers. See [Social authentication setup](docs/SOCIAL_AUTH.md) for exact callback URLs and security limitations. UI does not simulate a successful login.

The sidebar can be **collapsed/expanded** on desktop, with a hamburger-controlled **slide-out drawer** and overlay on tablet/mobile. Current navigation state is remembered locally. The layout follows the uploaded light UI design kit.

**Upgrade existing data without deleting volumes:**

```bash
git pull origin main
# Add AUTH_SESSION_SECRET and OAuth provider credentials to your existing .env (optional).
# Create a strong secret with: python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
docker compose up -d --build
docker compose ps -a
docker compose run --rm --no-deps api pytest -q
curl -s http://localhost:8080/api/auth/providers
curl -s http://localhost:8080/api/auth/me
```

Migration `0006_user_social_auth` retains earlier jobs and adds nullable user ownership.
Old jobs without an owner remain admin-key-visible only. **Never run `docker compose down -v` on existing production data.**

## Video review, translated captions and URL near-live processing

The redesigned Job Details panel now uses **real HTML5 video playback** with seeking, subtitles and transcription/translation text review. An authenticated user or trusted admin API key can mint a short-lived, job-specific playback grant; **the API key is not embedded in the video URL**. The player streams MP4 bytes using HTTP Range requests via S3 object storage. When real subtitle mode is enabled and the job completes, the player also requests a UTF-8 WebVTT track from the saved translated SRT. Video exports are normalized to **H.264 + AAC**, with selectable MP4 `mov_text` subtitle tracks for broad browser compatibility.

The provider requires original audio. If the stream contains no intelligible speech, the job fails explicitly instead of fabricating a translation. Previous demo jobs may retain an unplayable codec; reprocessing them into new H.264/AAC output may be necessary.

### Direct online URL translation (bounded near-live captions)

With `MODEL_MODE=real_subtitles`, allowlisted public HTTP(S) MP4/HLS stream URLs are recorded in **closed chunks** (around 12 seconds). When a chunk closes, its audio is processed by the locally loaded offline ASR + MT models and partial translated text is persisted to PostgreSQL. The Job Details view refreshes approximately every 8 seconds, allowing intermediate caption text to appear as inference completes. At the end of the selected **15–120 second** capture, the segments are merged and exported to S3 as an MP4 with a translated subtitle track and downloadable SRT. Latency depends on CPU/GPU and actual model speed; **this is not continuous zero-latency simultaneous speech translation**.

Server-side URL ingestion is **admin-only by default** (`STREAM_URL_ALLOW_USERS=false`). Administrators must supply an explicit `STREAM_ALLOWED_HOSTS` allowlist in the private `.env`. Re-enabling URL submission for ordinary social users without an egress firewall is not recommended: FFmpeg manifests/redirects can bypass a simple host allowlist, risking SSRF. Never allow untrusted public URLs on a network with unrestricted access to PostgreSQL, Redis, MinIO or cloud metadata.

### Local model and browser E2E tests

```bash
# Demo mode: verify upload -> queue -> FFmpeg -> completed MP4 -> HTTP 206 preview
python3 scripts/e2e-demo.py

# Offline subtitle mode: requires approved model weights in models/asr, models/mt
docker compose -f compose.yaml -f compose.real.yaml up -d --build
docker compose -f compose.yaml -f compose.real.yaml run --rm --no-deps api pytest -q
```

Real-mode jobs are rejected with HTTP 503 when model files are absent, rather than falsely marked ready. Real-mode speech quality and end-to-end throughput have not been tested on your hardware. The pipeline creates **translated subtitles, not translated voice dubbing**.

## Monthly model evaluation

After placing real human-reviewed English/Khmer evaluation samples in the private `benchmarks/private/` directory, use [the monthly model quality benchmark](benchmarks/README.md) to measure source-language CER/WER, translated text chrF++, and inference duration for each direction. It can be scheduled on a trusted server each month, but the repository does not contain your dataset or automatically retrain model weights. No accuracy benchmark is fabricated. If you meant **a monthly paid AI model subscription** or **automatic monthly retraining**, please specify which: they require different architectures.

## API
- `GET /api/health/live`, `GET /api/health/ready`
- `GET /api/models` with `X-API-Key`
- `POST /api/media` multipart file with `X-API-Key`
- `POST /api/jobs` JSON `{ "media_id":"...", "source_lang":"en", "target_lang":"km" }`
- `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/download`

## Tests
```bash
docker compose run --rm --no-deps api pytest -q
```
This checks contracts, not full infrastructure integration. For CI without Docker, `cd backend && pip install -r requirements.txt && pytest -q` (requires dependency download).

## Offline / air gap
Runtime uses only local DB/Redis/MinIO and keeps model network flags disabled; however **the initial Docker build needs internet** for Docker images, npm, APT and Python packages. To deploy air-gapped, first pre-build/pull all images on an online host, run `docker image save` into tarballs, copy them securely to the air-gapped host and `docker load`. Verify checksums, base-image versions, model licenses, and that no services call outside endpoints. Compose alone does not enforce a network egress firewall.

## Security and scope
The demo uses a single API key and does not provide per-user RBAC; it is for a trusted internal research environment, not exposed public internet. Bind web to localhost using host firewall or update Compose port mapping for local-only development; use HTTPS gateway in production. Container images are tagged and should be further pinned by digest for reproducible production deployments.

## Limitations / next milestone
- No real Khmer/English ASR, MT, TTS, or live streaming yet.
- No production outbox/lease/replay, tenant isolation, user authentication, rate limits, virus scanning, model provenance validation or rigorous E2E benchmarking.
- See `docs/REAL_MODELS.md` for a realistic Phase 2 model integration strategy.
