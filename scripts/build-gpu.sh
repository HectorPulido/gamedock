#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
docker build -t gamedock-runtime:local runtime
for vendor in nvidia amd intel; do
  docker build --target "$vendor" -t "gamedock-runtime-gpu-$vendor:local" -f runtime/gpu/Dockerfile runtime/gpu
done
