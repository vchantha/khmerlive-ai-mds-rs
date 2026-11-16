# KhmerLive AI — Flow Architecture & Acceptance Contract

Status: **MVP architecture implemented in part; real offline inference and research extensions not yet validated.**
This document maps the proposed research process drawing to *actual code* and specifies
the checks required before we call a release ready.

## A. End-to-end stages

| Stage in drawing | Implementation | Validation / limitation |
| --- | --- | --- |
| Input English video | `backend/app/main.py`, `backend/app/tasks.py` | MP4 upload and controlled URL/YouTube sources. MKV/MOV uploads shown in the conceptual drawing are **not supported** by the upload endpoint. |
| Audio extraction | `backend/app/tasks.py` (FFmpeg) | Verify 16-kHz audio extraction with speech-bearing MP4. |
| Whisper ASR | `backend/app/real_inference.py` | Real mode requires offline pre-provisioned weights. |
| M2M100 English→Khmer | `backend/app/real_inference.py` | Compare initial translation to human references. |
| Optional local LLM post-edit | `backend/app/llm_postedit.py`, `compose.ollama.yaml`, `compose.vllm.yaml` | Opt-in; tests mock local HTTP inference. No actual Khmer model quality validation yet. |
| Khmer MMS TTS | `backend/app/khmer_tts.py` | Needs real-model evaluation of audible synthesized Khmer and timing. |
| Video muxing + subtitles | `backend/app/tasks.py` (FFmpeg) | Requires end-to-end H.264/AAC/mov_text output validation. |
| Final assets | PostgreSQL job metadata, S3-compatible storage | Verify playback, downloads, and persistent metadata after restart. |

Real processing runs only with `MODEL_MODE=real_subtitles`; demo mode is not dubbed translation.
The named `real_subtitles` mode may also dub Khmer if `ENABLE_KHMER_DUBBING=true`.

### LLM output guards and readiness (2026-11-17)

Every LLM line passes `validate_khmer_line` (`backend/app/llm_postedit.py`) before it can replace
the M2M100 draft; a rejected line keeps the draft and is logged as `kept original (rejected output)`
with the reason. The guards reject: empty, multi-line, control/U+FFFD characters, no Khmer script,
mostly-Latin output, a leading Khmer dependent sign, an echo of the English, output >3× or <35% of
the draft length, and **any number the draft kept that the LLM dropped or changed, or a number it
invented** (Khmer digits ០–៩ count as the same number). Code fences, quotes and "Khmer:" labels
are stripped first.

Measured on the target machine (Qwen3-4B-Instruct via Ollama 0.12.10, temperature 0): for
"The course has 12 lessons and costs 50 dollars." the LLM changed `50 ដុល្លារ` to `5 ដុល្លារ` in
2 of 2 runs. Before this guard the corrupted line was accepted as "edited"; now it is rejected and
the correct draft is dubbed. The guards are safety checks, not a quality metric: lines that pass
still need human adequacy/fluency review.

- Lines returned identical to the draft are logged `unchanged`, not `edited`, so E1 statistics
  count real edits only.
- `LLM_MAX_RETRIES` (default 1) retries timeouts and HTTP 429/5xx within the job's time budget;
  connection refusals (server down) and rejected outputs are not retried.
- `LLM_PROVIDER=none` keeps the machine translation without any network call.
- `prompt_version` (hash of the active prompt) is stored in the job's `timings.llm` with provider,
  model and mode, and in the pipeline log, so results can be tied to the exact prompt.
- Readiness: `/api/system` reports `ready` only when the server answers **and** the configured
  model is installed. A real inference check runs through the same guards:
  `docker compose exec worker python -m app.llm_postedit --smoke` (exit 0 = pass) or
  `POST /api/system/llm/smoke` (admin only).

## B. Infrastructure responsibilities

- React frontend and FastAPI are the user-facing application.
- PostgreSQL stores persistent job, user, and media metadata; Redis handles task coordination.
- S3-compatible object storage holds original and generated media; Celery runs AI workloads.
- All model serving runs on the internal Docker network. No public LLM API is necessary.
- `compose.ollama.yaml` is the CPU-first local LLM option; `compose.vllm.yaml`
  is the optional NVIDIA GPU option. **Do not start both on a 16-GB RAM host.**
- The 4B LLM does not guarantee Khmer quality; the model needs human-reviewed evaluation.
- LLM post-editing keeps ASR timestamps unchanged. That alone does not optimize audible
  TTS duration; a duration-aware research algorithm remains future work.

## C. Research phases

1. **Baseline (E0)**: M2M100 outputs + complete MP4 pipeline, no LLM.
2. **Prompt post-editing (E1/E2)**: small/large local LLM, fixed dataset and prompt.
   E0 vs E1 tooling and a frozen FLORES-200 held-out set (1012 sentences, split by article)
   are in place: see `docs/EVALUATION_E0_E1.md`. In-domain video references still need a translator.
3. **LoRA/QLoRA (E3)**: separate GPU-based training code, not implemented yet.
4. **Context-aware (E4)**: evaluate neighboring segments; not implemented yet.
5. **Duration-constrained (E5)**: implement and compare alignment metrics using
   actual Khmer TTS duration; not implemented yet.

Keep dataset splits separated by video/speaker. Human reviewers must evaluate
adequacy, fluency, omissions, names, numbers and timing. Preserve baseline
translations, edited translations, model/prompt versions and timing metrics as
separate research artifacts; complete versioned research provenance is not yet
implemented in the current database schema.

## D. Release gates

1. Compose `config` validates for base, Ollama overlay and optional vLLM overlay.
2. Frontend and backend images build in CI.
3. Backend test suite passes with `python -m pytest -q` inside Docker.
4. Demo mode boots and demo-video upload/playback test passes.
5. On the target Ubuntu machine: all offline model weights are present and
   the chosen inference server passes an actual Khmer-segment request.
6. On the target machine with outbound network blocked: a rights-cleared English
   MP4 completes with audible Khmer audio, synchronized subtitles and playable MP4.
7. Measure peak RAM, CPU load, processing latency, error rate and segment-duration
   mismatch; retain an independent human-reviewed test split.
8. Review security, model licenses, operational backups and recovery before production.

**Do not merge as production-ready solely because CI, mocked adapter tests, or
Docker Compose configuration checks pass.** The real offline quality tests and
GPU fine-tuning need separate hardware-backed evidence.

## E. CI evidence

- `.github/workflows/ci.yml` builds, starts, runs backend tests, checks API readiness
  and processes a *demo* video. It does not validate real ASR, MT, TTS or local LLM weights.
- `.github/workflows/llm-adapter.yml` tests the post-edit adapter with mocked HTTP
  responses and validates Docker Compose overlays. It does not load a live LLM.
- `docs/OFFLINE_OLLAMA.md` and `docs/OFFLINE_VLLM.md` explain runtime provisioning.

Tests must distinguish mocked behavior, demo E2E, and actual offline inference.
