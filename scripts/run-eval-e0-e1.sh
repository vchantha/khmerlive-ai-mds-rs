#!/usr/bin/env bash
# E0 vs E1 on a frozen held-out set, using the worker image and the running Ollama/vLLM.
#
#   ./scripts/run-eval-e0-e1.sh                         # full FLORES held-out test (~30-60 min on GPU)
#   ./scripts/run-eval-e0-e1.sh --limit 40              # quick smoke run (marked partial)
#   ./scripts/run-eval-e0-e1.sh --dataset /bench/private/eval/video-en-km-v1
#
# Results: benchmarks/reports/runs/<run-id>/ (REPORT.md, scores.json, hypotheses.jsonl,
# human_eval_sheet.csv, human_eval_key.json, config.json). Nothing is downloaded.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f benchmarks/private/eval/flores200-en-km-v1/DATASET_CARD.json ]] || [[ " $* " == *" --dataset "* ]] || {
  echo "Build the evaluation set first: python3 scripts/build-eval-set.py flores --tarball ..." >&2; exit 1; }
mkdir -p benchmarks/reports/runs
ARGS=("$@"); [[ " $* " == *" --dataset "* ]] || ARGS=(--dataset /bench/private/eval/flores200-en-km-v1 "$@")
docker compose run --rm --no-deps -T \
  --user "$(id -u):$(id -g)" -e HOME=/tmp -e HF_HUB_OFFLINE=1 -e SACREBLEU=/bench/private/sacrebleu \
  -e GIT_COMMIT="$(git rev-parse HEAD)$(git diff --quiet HEAD -- backend scripts || echo '-dirty')" \
  -v "$PWD/backend:/app:ro" \
  -v "$PWD/scripts:/bench-scripts:ro" \
  -v "$PWD/benchmarks/private:/bench/private:ro" \
  -v "$PWD/benchmarks/reports:/bench/reports" \
  --entrypoint python worker /bench-scripts/run-eval-e0-e1.py "${ARGS[@]}"
