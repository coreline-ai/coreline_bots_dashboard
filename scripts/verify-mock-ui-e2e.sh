#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MOCK_UI_BASE_URL="${MOCK_UI_BASE_URL:-http://127.0.0.1:9082}"
RUNNER="${RUNNER:-./scripts/run-local-multibot.sh}"
SOURCE_CONFIG_PATH="${SOURCE_CONFIG_PATH:-config/bots.multibot.yaml}"
REUSE_LIVE_STACK="${REUSE_LIVE_STACK:-0}"
TMP_CONFIG_PATH=""
TMP_RUNTIME_DIR=""

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required binary: $1" >&2
    exit 1
  fi
}

health_ok() {
  curl -fsS "$1/healthz" >/dev/null 2>&1
}

cleanup() {
  if [[ "$REUSE_LIVE_STACK" == "1" ]]; then
    return 0
  fi
  if [[ -n "$TMP_CONFIG_PATH" && -n "$TMP_RUNTIME_DIR" ]]; then
    CONFIG_PATH="$TMP_CONFIG_PATH" RUNTIME_DIR="$TMP_RUNTIME_DIR" "$RUNNER" stop >/dev/null 2>&1 || true
  fi
  if [[ -n "$TMP_CONFIG_PATH" ]]; then
    rm -f "$TMP_CONFIG_PATH"
  fi
  if [[ -n "$TMP_RUNTIME_DIR" ]]; then
    rm -rf "$TMP_RUNTIME_DIR"
  fi
}

require_bin curl
require_bin npm
require_bin npx
require_bin mktemp

if [[ "$REUSE_LIVE_STACK" != "1" ]]; then
  TMP_CONFIG_PATH="$(mktemp -t bots-multibot-e2e)"
  TMP_RUNTIME_DIR="$(mktemp -d -t runlogs-multibot-e2e)"
  cp "$SOURCE_CONFIG_PATH" "$TMP_CONFIG_PATH"
fi
trap cleanup EXIT

if ! health_ok "$MOCK_UI_BASE_URL"; then
  if [[ "$REUSE_LIVE_STACK" == "1" ]]; then
    echo "mock server unavailable for live verification: $MOCK_UI_BASE_URL" >&2
    exit 1
  fi
  echo "mock server down. trying detached start..."
  CONFIG_PATH="$TMP_CONFIG_PATH" RUNTIME_DIR="$TMP_RUNTIME_DIR" "$RUNNER" start || true
fi
if ! health_ok "$MOCK_UI_BASE_URL"; then
  echo "mock server unavailable: $MOCK_UI_BASE_URL" >&2
  exit 1
fi

pushd tests/e2e >/dev/null
if [[ ! -d node_modules ]]; then
  npm install
fi
npx playwright install chromium
MOCK_UI_BASE_URL="$MOCK_UI_BASE_URL" npx playwright test
popd >/dev/null

if [[ "$REUSE_LIVE_STACK" == "1" ]]; then
  if ! health_ok "$MOCK_UI_BASE_URL"; then
    echo "live stack became unavailable after playwright: $MOCK_UI_BASE_URL" >&2
    exit 1
  fi
fi
