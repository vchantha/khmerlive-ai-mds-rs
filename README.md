# KhmerLive AI — Docker Compose Research MVP

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

The redesigned dark-mode interface is served on `http://localhost:8080`. It provides:
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
