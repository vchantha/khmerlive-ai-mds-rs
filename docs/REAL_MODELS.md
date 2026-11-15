# Real model integration gate

The provided stack uses `MODEL_MODE=demo` by design: its outputs are explicit placeholders and its MP4 export is an unchanged-content remux. **No real Khmer ASR, translation, TTS or streaming is present.** Switching `MODEL_MODE` to any other value fails safely.

To add real inference, implement and benchmark the `ASR` and `MT` protocols in `backend/app/adapters.py`, plus a TTS protocol and timestamp alignment. Download immutable model revisions onto an online staging machine; archive model weights, tokenizer, normalizer, wheelhouse and hashes; verify licenses (including training data and voice rights), offline behavior and model quality in both language directions. Keep `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` in production workers. Do not use CC-BY-NC models commercially.

Before production, add strong per-user authorization, audit trails, durable dispatch/outbox, idempotent worker leases, scanning/FFmpeg isolation, signed storage access, secrets rotation, backups, tests with real media and disaster recovery. These are deliberate MVP limitations, not production guarantees.
