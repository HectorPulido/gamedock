#!/usr/bin/env bash
# Isolated TLS/video QA; never touches existing game containers.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
qa_dir=$(mktemp -d /tmp/gamedock-streaming-qa.XXXXXX)
mkdir -p "$qa_dir/tls" /tmp/gamedock-streaming-artifacts
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$qa_dir/tls/privkey.pem" \
  -out "$qa_dir/tls/fullchain.pem" -days 2 -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,DNS:gamedock-bandwidth-qa-portal-1,IP:127.0.0.1' 2>/dev/null
chmod 600 "$qa_dir/tls/privkey.pem"
python3 - "$qa_dir" <<'PY'
from pathlib import Path
import secrets, sys
p=Path(sys.argv[1])/'qa.env'
p.write_text('ADMIN_PASSWORD='+secrets.token_urlsafe(24)+'\nPUBLIC_URL=https://gamedock-bandwidth-qa-portal-1:8080\nTLS_DIRECTORY='+sys.argv[1]+'/tls\n')
p.chmod(0o600)
PY
qa_compose=(docker compose -p gamedock-bandwidth-qa --env-file "$qa_dir/qa.env" -f compose.yaml -f examples/https/compose.yaml)
trap '"${qa_compose[@]}" down -v; rm -rf "$qa_dir"' EXIT
"${qa_compose[@]}" down -v
docker build -t gamedock-runtime:bandwidth-qa runtime
docker run --rm --entrypoint python3 -v "$PWD/tests/test_xpra_bandwidth.py:/test.py:ro" gamedock-runtime:bandwidth-qa /test.py -v
docker build -t gamedock-portal:local .
docker build -f tests/Dockerfile.browser -t gamedock-browser-qa:local .
PORT=18092 "${qa_compose[@]}" up -d --build --wait
docker run --rm --network gamedock-bandwidth-qa_default \
  -e QA_URL=https://gamedock-bandwidth-qa-portal-1:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock -v "$qa_dir/qa.env:/qa.env:ro" \
  -v "$PWD:/app:ro" -v /tmp/gamedock-streaming-artifacts:/artifacts \
  gamedock-browser-qa:local python tests/bandwidth_browser.py
docker run --rm --network gamedock-bandwidth-qa_default \
  -e QA_URL=https://gamedock-bandwidth-qa-portal-1:8080 \
  -e QA_EXPECT_H264=0 -e QA_BROWSER_EXECUTABLE= \
  -v /var/run/docker.sock:/var/run/docker.sock -v "$qa_dir/qa.env:/qa.env:ro" \
  -v "$PWD:/app:ro" -v /tmp/gamedock-streaming-artifacts:/artifacts \
  gamedock-browser-qa:local python tests/bandwidth_browser.py
