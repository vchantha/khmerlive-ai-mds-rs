#!/usr/bin/env bash
# Non-destructive runtime diagnostics. NEVER prints .env or credentials.
set -u
echo "== Docker Compose services =="
docker compose ps -a || true
echo
echo "== Migration logs (most relevant) =="
docker compose logs --no-color --tail=160 migrate || true
echo
echo "== Migration image and revision discovery =="
docker compose run --rm --no-deps migrate sh -c 'pwd; python -c "import app, alembic, sqlalchemy; print(\"Python imports OK\")"; alembic -c /app/alembic.ini heads' || true
echo
echo "== PostgreSQL health =="
docker compose ps db || true
echo
echo "== S3 service logs =="
docker compose logs --no-color --tail=60 minio minio-init || true
echo
echo "Do not run docker compose down -v. Copy the error lines above if migration remains failed."
