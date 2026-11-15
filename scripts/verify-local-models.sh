#!/usr/bin/env bash
set -euo pipefail
printf 'Offline model manifest check:\n'
if test -f models/manifest.lock.json; then python3 -m json.tool models/manifest.lock.json >/dev/null; else echo 'No model lock found'; exit 1; fi
find models -type l -print -quit | grep -q . && { echo 'Model symlinks not allowed in air-gap bundle'; exit 1; } || true
printf 'Manifest syntax OK. This does NOT validate accuracy or licensing.\n'
