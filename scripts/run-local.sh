#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export RUN_LOCAL_ALIAS="$0"
exec "$ROOT_DIR/scripts/run-local-fixed.sh" "${1:-up}" "${@:2}"
