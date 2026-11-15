#!/usr/bin/env bash
# Monthly offline model quality regression runner. Run as the deployment user.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f benchmarks/private/manifest.jsonl ]]; then
  echo "No human-reviewed monthly benchmark manifest at benchmarks/private/manifest.jsonl" >&2
  exit 2
fi
if [[ ! -f models/asr/model.bin || ! -f models/mt/config.json ]]; then
  echo "Offline ASR or MT assets are missing; cannot evaluate quality" >&2
  exit 2
fi
mkdir -p benchmarks/reports
docker compose -f compose.yaml -f compose.real.yaml run --rm --no-deps \
  -v "$PWD/scripts:/bench-scripts:ro" \
  -v "$PWD/benchmarks/private:/benchmarks/private:ro" \
  -v "$PWD/benchmarks/reports:/benchmarks/reports" \
  worker python /bench-scripts/monthly-model-eval.py \
  --manifest /benchmarks/private/manifest.jsonl \
  --report-dir /benchmarks/reports \
  --asr /models/asr --mt /models/mt
