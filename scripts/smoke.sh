#!/usr/bin/env bash
set -euo pipefail
base="${1:-http://localhost:8080}"
curl -fsS "$base/api/health/live"; echo
curl -fsS "$base/api/health/ready"; echo
printf 'Health endpoints passed. To test authenticated upload, use the UI.\n'
