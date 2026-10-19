#!/usr/bin/env bash
# Current generic Selkies contract checks; does not claim real-browser throughput.
set -Eeuo pipefail
exec "$(dirname "$0")/qa.sh" "$@"
