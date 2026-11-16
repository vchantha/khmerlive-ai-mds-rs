#!/usr/bin/env bash
# One-command deploy. Detects an NVIDIA GPU and picks the right Compose files, then
# saves them as COMPOSE_FILE in .env so later `docker compose ...` commands just work.
#
#   ./scripts/deploy.sh            # auto: GPU if available, else CPU
#   ./scripts/deploy.sh --cpu      # force CPU-only
#   ./scripts/deploy.sh --gpu      # force GPU (fails if Docker can't see the GPU)
#   ./scripts/deploy.sh --demo     # no AI models, placeholder output (quick UI test)
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-auto}"; MODE="${MODE#--}"
say(){ printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "Docker is not installed"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
[[ -f .env ]] || { say "Creating .env with random secrets"; ./scripts/init-env.sh; }

getenv(){ grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
setenv(){ if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi; }

gpu_ok(){ command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1 && docker info 2>/dev/null | grep -qi 'runtimes:.*nvidia'; }
if [[ "$MODE" == auto ]]; then
  if gpu_ok; then MODE=gpu; else MODE=cpu
    command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1 && \
      say "NVIDIA GPU found but Docker can't use it: install nvidia-container-toolkit (README → GPU). Using CPU."
  fi
fi
[[ "$MODE" == gpu ]] && ! gpu_ok && die "Docker has no NVIDIA runtime. See README → 'GPU setup'."

FILES="compose.yaml"
case "$MODE" in
  demo) setenv MODEL_MODE demo ;;
  cpu|gpu)
    [[ -f models/asr/model.bin && -f models/mt/config.json ]] || die "Models missing in ./models. Run: python3 scripts/download-models.py"
    setenv MODEL_MODE real_subtitles
    FILES="$FILES:compose.real.yaml"
    [[ "$MODE" == gpu ]] && FILES="$FILES:compose.gpu.yaml"
    if [[ "$(getenv LLM_POSTEDIT_ENABLED)" == true ]]; then
      FILES="$FILES:compose.ollama.yaml"
      [[ "$MODE" == gpu ]] && FILES="$FILES:compose.ollama-gpu.yaml"
    fi ;;
  *) die "Unknown mode '$MODE' (use --cpu, --gpu or --demo)";;
esac
setenv COMPOSE_FILE "$FILES"
export COMPOSE_FILE="$FILES"
say "Mode: $MODE   Compose files: ${FILES//:/ }"

docker compose config --quiet
say "Building and starting services (first GPU build downloads ~6 GB of CUDA libraries)"
docker compose up -d --build

if [[ "$MODE" != demo ]]; then
  if [[ ! -f models/mt-ct2/model.bin ]]; then
    say "Converting the translation model to CTranslate2 (one time, ~1 min)"
    WORKER_IMAGE="khmerlive-worker:real-$MODE" ./scripts/convert-mt-ct2.sh
    docker compose restart worker
  fi
  if [[ "$(getenv LLM_POSTEDIT_ENABLED)" == true ]]; then
    MODEL="$(getenv OLLAMA_MODEL)"; MODEL="${MODEL:-qwen3:4b-instruct}"
    docker compose exec -T ollama ollama list | grep -q "^${MODEL} " || {
      say "Pulling LLM $MODEL (needs Internet once)"; docker compose exec -T ollama ollama pull "$MODEL"; }
  fi
fi

say "Waiting for the API"
for _ in $(seq 1 60); do
  docker compose exec -T api python -c "import httpx;httpx.get('http://localhost:8000/api/health/ready',timeout=2).raise_for_status()" >/dev/null 2>&1 && break
  sleep 2
done
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
say "Done → http://localhost:$(getenv WEB_PORT | grep . || echo 8080)   (sign in with API_KEY from .env)"
[[ "$MODE" == gpu ]] && say "GPU check: docker compose exec ollama ollama ps   (PROCESSOR should be 100% GPU)"
exit 0
