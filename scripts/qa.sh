#!/usr/bin/env bash
# Current Selkies contract/unit checks. No running player containers are changed.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
qa_image=${GAMEDOCK_QA_IMAGE:-gamedock-portal:selkies-qa}
docker build -t "$qa_image" .
docker run --rm -v "$PWD:/app:ro" "$qa_image" python -m unittest discover -s tests -v
if command -v node >/dev/null 2>&1; then
  node tests/selkies_viewer_test.cjs
else
  docker run --rm -v "$PWD:/app:ro" -w /app node:22-bookworm-slim node tests/selkies_viewer_test.cjs
fi
printf '%s
' 'Selkies contract checks passed; real-browser/GPU/load acceptance is separate (VALIDATION.md).'
