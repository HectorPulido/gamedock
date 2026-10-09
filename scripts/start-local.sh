#!/usr/bin/env bash
# Build and start a self-contained local demo. Existing credentials are preserved.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
docker info >/dev/null
docker compose version >/dev/null
if [[ ! -f .env ]]; then
    (umask 077; docker run --rm python:3.12-slim python -c 'import secrets; print("ADMIN_USER=admin\nADMIN_PASSWORD=" + secrets.token_urlsafe(24) + "\nPUBLIC_URL=http://localhost:8080\nBIND_ADDRESS=127.0.0.1\nPORT=8080")' > .env)
fi
docker build -t gamedock-runtime:local runtime
docker build -t gamedock-openttd:local examples/openttd
docker compose up -d --build --wait
docker compose exec -T -e "GAMEDOCK_DEMO_PROFILE=$(cat examples/openttd/profile.json)" portal python - < scripts/bootstrap-demo.py
