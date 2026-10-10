#!/usr/bin/env bash
# Dedicated QA project only. Leaves the QA portal available for inspection.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('/tmp/gamedock-qa.env')
if not p.exists():
    p.write_text('ADMIN_PASSWORD=' + secrets.token_urlsafe(24) + '\nPUBLIC_URL=http://gamedock-qa-portal-1:8080\n')
    p.chmod(0o600)
PY
docker build -t gamedock-runtime:local runtime
docker run --rm --entrypoint python3 -v "$PWD/tests/test_xpra_idle.py:/tmp/test_xpra_idle.py:ro" gamedock-runtime:local /tmp/test_xpra_idle.py -v
docker build -t gamedock-portal:local .
docker build -t gamedock-openttd:local examples/openttd
docker build -f tests/Dockerfile.browser -t gamedock-browser-qa:local .
docker run --rm -v "$PWD:/app:ro" gamedock-portal:local python -m unittest discover -s tests -v
PORT=18088 docker compose -p gamedock-qa --env-file /tmp/gamedock-qa.env up -d --build --wait
QA_RECREATE=1 python3 tests/live.py
python3 tests/idle_live.py
mkdir -p /tmp/gamedock-artifacts
docker run --rm --network gamedock-qa_default -e QA_URL=http://gamedock-qa-portal-1:8080 -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/gamedock-qa.env:/qa.env:ro -v "$PWD:/app:ro" -v /tmp/gamedock-artifacts:/artifacts gamedock-browser-qa:local python tests/browser.py
docker run --rm --network gamedock-qa_default -e QA_URL=http://gamedock-qa-portal-1:8080 -v /tmp/gamedock-qa.env:/qa.env:ro -v "$PWD:/app:ro" -v /tmp/gamedock-artifacts:/artifacts gamedock-browser-qa:local python tests/game_browser.py
docker run --rm --network gamedock-qa_default -e QA_URL=http://gamedock-qa-portal-1:8080 -v /tmp/gamedock-qa.env:/qa.env:ro -v "$PWD:/app:ro" -v /tmp/gamedock-artifacts:/artifacts gamedock-browser-qa:local python tests/admin_browser.py
docker run --rm --network gamedock-qa_default -e QA_URL=http://gamedock-qa-portal-1:8080 -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/gamedock-qa.env:/qa.env:ro -v "$PWD:/app:ro" -v /tmp/gamedock-artifacts:/artifacts gamedock-browser-qa:local python tests/customization_browser.py
docker run --rm --network gamedock-qa_default -e QA_URL=http://gamedock-qa-portal-1:8080 -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/gamedock-qa.env:/qa.env:ro -v "$PWD:/app:ro" -v /tmp/gamedock-artifacts:/artifacts gamedock-browser-qa:local python tests/streaming_browser.py
docker run --rm --network gamedock-qa_default -e QA_URL=http://gamedock-qa-portal-1:8080 -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/gamedock-qa.env:/qa.env:ro -v "$PWD:/app:ro" -v /tmp/gamedock-artifacts:/artifacts gamedock-browser-qa:local python tests/notifications_browser.py
echo 'QA passed. Screenshots: /tmp/gamedock-artifacts'
