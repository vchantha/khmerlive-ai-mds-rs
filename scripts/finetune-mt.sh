#!/usr/bin/env bash
# Fine-tune the translation model on your verified lines, evaluate it, and deploy it only if it's better.
#
#   ./scripts/finetune-mt.sh             # train + evaluate; deploy if chrF++ improves by >= 1 point
#   ./scripts/finetune-mt.sh --no-deploy # train + evaluate only
#   ./scripts/finetune-mt.sh --rollback  # go back to the original translation model
#
# Needs: ~100+ verified lines (300+ recommended) from the job page's "Review translation",
# Internet once (installs the PEFT library into the training container).
# The worker is paused during training so the GPU is free; queued jobs wait and then continue.
set -euo pipefail
cd "$(dirname "$0")/.."
say(){ printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
getenv(){ grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
setenv(){ if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi; }
unsetenv(){ sed -i "/^$1=/d" .env; }

if [[ "${1:-}" == "--rollback" ]]; then
  unsetenv MT_CT2_PATH; docker compose up -d worker
  say "Rolled back to the original translation model (models/mt-ct2)."; exit 0
fi
DEPLOY=1; [[ "${1:-}" == "--no-deploy" ]] && DEPLOY=0

IMAGE=$(docker compose config --images worker | head -1)
GPU_ARGS=(); docker info 2>/dev/null | grep -qi 'runtimes:.*nvidia' && [[ "$IMAGE" == *gpu* ]] && GPU_ARGS=(--gpus all)
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p models/finetune
DATA="models/finetune/corrections-$STAMP.jsonl"

say "Exporting verified lines"
curl -fsS -H "X-API-Key: $(getenv API_KEY)" "http://localhost:$(getenv WEB_PORT | grep . || echo 8080)/api/dataset/corrections?format=jsonl" -o "$DATA" \
  || die "Could not export the dataset (is the stack running?)"
say "$(wc -l < "$DATA") verified lines → $DATA"

say "Pausing the worker and freeing the GPU for training"
docker compose exec -T worker python -c "from app.llm_postedit import unload_llm; unload_llm()" >/dev/null 2>&1 || true
docker compose stop worker >/dev/null
# 'up -d' (not 'start') so a changed MT_CT2_PATH in .env takes effect.
trap 'say "Resuming the worker"; docker compose up -d worker >/dev/null 2>&1' EXIT

# Held-out evaluation sentences must never be trained on (scripts/build-eval-set.py writes the keys).
EXCLUDE=()
for keys in benchmarks/private/eval/*/eval_source_keys.txt; do
  [[ -f "$keys" ]] || continue
  name=$(basename "$(dirname "$keys")"); cp "$keys" "models/finetune/eval-keys-$name.txt"
  EXCLUDE+=(--exclude-keys "/models/finetune/eval-keys-$name.txt")
done

OUT="/models/mt-ft-$STAMP"
docker run --rm "${GPU_ARGS[@]}" --user "$(id -u):$(id -g)" -e HOME=/tmp -e HF_HUB_OFFLINE=1 \
  -v "$PWD/models:/models" -v "$PWD/backend/training:/training:ro" -v "$PWD/scripts:/scripts:ro" "$IMAGE" sh -c "
    pip install --quiet --user --no-warn-script-location peft==0.15.2 &&
    python /training/finetune_mt.py --data /models/finetune/$(basename "$DATA") --out $OUT ${EXCLUDE[*]} &&
    python /scripts/convert_mt_ct2.py $OUT ${OUT}-ct2"
REPORT="models/mt-ft-$STAMP/report.json"
[[ -f "$REPORT" ]] || die "Training did not produce a report"
cp "$REPORT" "models/mt-ft-$STAMP-ct2/report.json"
RECOMMEND=$(python3 -c "import json;print(json.load(open('$REPORT'))['recommend_deploy'])")
GAIN=$(python3 -c "import json;r=json.load(open('$REPORT'));print(f\"{r['base_chrf']} -> {r['finetuned_chrf']} chrF++ ({r['gain']:+})\")")
say "Held-out score: $GAIN   (examples in $REPORT)"

if [[ "$DEPLOY" == 1 && "$RECOMMEND" == True ]]; then
  setenv MT_CT2_PATH "/models/mt-ft-$STAMP-ct2"
  say "Deployed: MT_CT2_PATH=/models/mt-ft-$STAMP-ct2 (undo with ./scripts/finetune-mt.sh --rollback)"
elif [[ "$RECOMMEND" != True ]]; then
  say "Not deployed: the fine-tuned model isn't clearly better yet. Collect more verified lines and try again."
else
  say "Not deployed (--no-deploy). To use it: set MT_CT2_PATH=/models/mt-ft-$STAMP-ct2 in .env and restart the worker."
fi
