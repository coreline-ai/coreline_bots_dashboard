#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:16-alpine}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-telegram_bot_new_postgres_it}"
POSTGRES_PORT="${POSTGRES_PORT:-54329}"
POSTGRES_USER="${POSTGRES_USER:-tg}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-tg}"
POSTGRES_DB="${POSTGRES_DB:-telegram_bot_new}"
KEEP_POSTGRES="${KEEP_POSTGRES:-0}"
TEST_POSTGRES_URL="${TEST_POSTGRES_URL:-postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}}"

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required binary: $1" >&2
    exit 1
  fi
}

cleanup() {
  if [[ "$KEEP_POSTGRES" == "1" ]]; then
    return 0
  fi
  docker rm -f "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true
}

wait_for_postgres() {
  local i
  for i in $(seq 1 40); do
    if docker exec "$POSTGRES_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

require_bin docker
require_bin "$PYTHON_BIN"

if ! docker info >/dev/null 2>&1; then
  echo "docker daemon unavailable. start Docker first." >&2
  exit 1
fi

trap cleanup EXIT

docker rm -f "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true
docker run -d \
  --name "$POSTGRES_CONTAINER" \
  -e "POSTGRES_USER=$POSTGRES_USER" \
  -e "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
  -e "POSTGRES_DB=$POSTGRES_DB" \
  -p "${POSTGRES_PORT}:5432" \
  "$POSTGRES_IMAGE" >/dev/null

if ! wait_for_postgres; then
  echo "postgres readiness check failed for container: $POSTGRES_CONTAINER" >&2
  exit 1
fi

echo "running postgres integration tests with TEST_POSTGRES_URL=$TEST_POSTGRES_URL"
TEST_POSTGRES_URL="$TEST_POSTGRES_URL" "$PYTHON_BIN" -m pytest -q tests/test_repository_postgres_integration.py
echo "postgres integration tests passed"
