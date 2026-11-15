#!/usr/bin/env bash
set -euo pipefail
if [[ -e .env ]]; then
  echo '.env already exists; refusing to overwrite.' >&2
  exit 1
fi
python3 - <<'PY'
from pathlib import Path
import secrets
p=Path('.env.example').read_text()
postgres=secrets.token_urlsafe(32)
minio=secrets.token_urlsafe(32)
api=secrets.token_urlsafe(32)
p=p.replace('change_this_long_password',postgres)
p=p.replace('change_this_long_minio_password',minio)
p=p.replace('change_this_to_a_long_random_api_key',api)
p=p.replace('change_this_auth_session_secret',secrets.token_urlsafe(48))
Path('.env').write_text(p)
Path('.env').chmod(0o600)
print('Wrote .env with randomized credentials; keep it private.')
PY
