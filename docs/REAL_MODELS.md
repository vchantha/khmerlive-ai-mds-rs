# Offline English ↔ Khmer Translation — Model Integration Status

The original `MODEL_MODE=demo` remains the safe default. In this mode, ASR and MT explicitly emit placeholder text and the video is an unchanged-content pass-through.

A new **optional** `real_subtitles` mode now has source-code adapters:
- `faster-whisper` local speech-to-text from an offline CTranslate2 Whisper model.
- Local `transformers` M2M100 multilingual translation (English↔Khmer).
- Timestamped translated UTF-8 SRT text and MP4 subtitle track (mov_text).
- Existing PostgreSQL job/queue state and S3 storage, plus SRT download.

**This does not equal a completed production translator.** We have not downloaded model weights into the user's server, benchmarked Khmer/English quality, or executed a complete real-model inference job in the user's environment. The real mode can fail during build/model loading or for certain videos; record and resolve those errors rather than claiming success. The original audio remains unchanged; **Khmer text-to-speech and dubbing are not implemented**.

## Model download and pinning

On an online staging computer:

```bash
python3 -m pip install huggingface-hub==0.30.2
python3 scripts/download-models.py --output models
```

The script resolves exact Git revisions and computes file SHA-256 hashes into `models/manifest.lock.json`. It intentionally leaves the weights out of Git (see `.gitignore`). Review the upstream model cards, exact checkpoint licenses, dependencies, dataset provenance and business-use permissions manually before redistribution or production use. Model licensing/quality cannot be determined from code alone.

Then from the project root on a host with suitable CPU/RAM:

```bash
docker compose -f compose.yaml -f compose.real.yaml up -d --build
docker compose -f compose.yaml -f compose.real.yaml run --rm --no-deps api pytest -q
```

Inspect worker logs, model paths and errors. For an inference smoke test, mount a short WAV into the worker container and run `python scripts/selftest-real.py --audio /path/in/container.wav --source en --target km` with correct paths to the local model assets. Use **two** spoken-language directions and native Khmer review. Do not confuse a successful MP4 subtitle-mux test with model accuracy.

## Remaining research work and release gates

- Benchmark ASR WER/CER and translation chrF++ on held-out Khmer and English datasets, including native human evaluation, named entities and telecom terminology.
- Validate subtitle duration, overlapping speech, diarization, segmentation and no-speech behavior.
- Build Khmer TTS with legally cleared voice data, robust phrase timing, bounded alignment, dubbing audio mixing and user choice of original/translated audio.
- Implement true continuous low-latency streaming ASR/MT/TTS; short HLS captures are **not** live translation.
- Add measured real-time factor, GPU/CPU memory and proper model/runtime and dataset licenses.
- Implement production outbox/worker checkpoint leases and safe failure/retry semantics.
- Introduce comprehensive authentication/RBAC and session controls, audit logs, secret rotation, backups, antivirus/media sandboxing and ingress egress restrictions.
- Test full air-gapped deployment on Ubuntu/RKE2 with pinned image digests and validated offline model assets.
