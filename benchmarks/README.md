# KhmerLive AI — Monthly Real Model Quality Check

This project does not ship **trained Khmer model weights** or claim perfect accuracy.
A monthly quality benchmark is available so the team can measure real improvements
and detect regressions after installing approved local Whisper + M2M100 model snapshots.

## Prepare private, human-reviewed bilingual samples

Create a private directory `benchmarks/private` (excluded by `.gitignore`) containing WAV audio and `manifest.jsonl`. Each row must have **genuine reference transcripts and translations** reviewed by an English/Khmer speaker. Example *schema* (do not use as a fake scored sample):

```json
{"audio":"english_sample.wav","source_lang":"en","target_lang":"km","source_reference":"<human-verified English transcript>","target_reference":"<human-verified Khmer translation>"}
```

Add real Khmer→English rows as well. The report is invalid without actual reference audio and matching human text.

## Run manually using the offline Docker worker

Install models into `models/asr` and `models/mt`, as described in the repository README. Bring up the real-mode stack and mount benchmark paths without exposing them:

```bash
docker compose -f compose.yaml -f compose.real.yaml up -d --build

mkdir -p benchmarks/private benchmarks/reports
docker compose -f compose.yaml -f compose.real.yaml run --rm --no-deps \
  -v "$PWD/scripts:/bench-scripts:ro" \
  -v "$PWD/benchmarks/private:/benchmarks/private:ro" \
  -v "$PWD/benchmarks/reports:/benchmarks/reports" \
  worker python /bench-scripts/monthly-model-eval.py \
    --manifest /benchmarks/private/manifest.jsonl \
    --report-dir /benchmarks/reports \
    --asr /models/asr --mt /models/mt \
    --max-cer 0.30 --min-chrf 45
```

The gates shown are **examples, not certified Khmer benchmarks**; choose thresholds based on your approved held-out evaluation dataset and domain requirements. The script exits 2 if a chosen gate fails, fails if model weights or references are missing, and records actual CER / WER / chrF++ and per-direction wall time in `benchmarks/reports/YYYY-MM-evaluation.json`.

## Schedule a monthly check (optional)

On the trusted Ubuntu machine you may use a rootless cron/systemd timer for the **first day of each month** to execute the same command and retain reports locally. Do not auto-publish private transcripts, voice files or reports to this public GitHub repository. Check available compute/disk and use a dedicated worker because CPU evaluation is potentially slow.

This is **monthly model evaluation**, not a monthly paid model subscription, continuous retraining, or proof of perfect translation. If you want monthly retraining/fine-tuning, gather opt-in labeled audio, review training rights, add a separate training workflow and evaluate against a strictly held-out set before deployment.

## Model release quality gates

Record exact ASR/MT model revisions and file hashes, held-out source CER/WER, target chrF++ scores, semantic critical-error counts, Khmer human reviewer feedback, processing latency, and tested hardware. Do not publish a release solely because a model file was downloaded or a container reported Healthy.

Online URL sessions provide **bounded near-live text updates** as each recording chunk is translated; they are not uninterrupted sub-second interpretation or voice-dubbed livestreams.
