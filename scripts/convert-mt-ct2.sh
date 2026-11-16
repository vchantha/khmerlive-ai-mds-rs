#!/usr/bin/env bash
# Convert the M2M100 translation model (models/mt) to CTranslate2 int8 (models/mt-ct2).
# Same model and output quality class, typically 3-4x faster translation on CPU and smaller in RAM.
# Runs offline inside the worker image; re-run after replacing models/mt. The worker uses it
# automatically (MT_ENGINE=auto) once models/mt-ct2/model.bin exists.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${WORKER_IMAGE:-khmerlive-worker:latest}"
if [[ ! -f models/mt/config.json ]]; then
  echo "models/mt is missing; run scripts/download-models.py first" >&2; exit 1
fi
if [[ -f models/mt-ct2/model.bin && "${FORCE:-0}" != "1" ]]; then
  echo "models/mt-ct2 already exists (set FORCE=1 to rebuild)"; exit 0
fi
rm -rf models/mt-ct2.tmp
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/models:/models" \
  -v "$PWD/scripts/convert_mt_ct2.py:/tmp/convert_mt_ct2.py:ro" "$IMAGE" \
  python /tmp/convert_mt_ct2.py /models/mt /models/mt-ct2.tmp
rm -rf models/mt-ct2 && mv models/mt-ct2.tmp models/mt-ct2
du -sh models/mt-ct2
echo "Done. Restart the worker to use it: docker compose up -d worker"
