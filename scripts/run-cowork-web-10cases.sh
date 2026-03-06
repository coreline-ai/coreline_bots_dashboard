#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUNNER="${RUNNER:-$ROOT_DIR/scripts/run-local-multibot.sh}"
SOURCE_CONFIG_PATH="${SOURCE_CONFIG_PATH:-$ROOT_DIR/config/bots.multibot.yaml}"
FIXTURE_PATH="${FIXTURE_PATH:-$ROOT_DIR/tests/e2e/fixtures/cowork_web_10cases.json}"
EFFECTIVE_FIXTURE_PATH=""
RESULT_ROOT="${RESULT_ROOT:-$ROOT_DIR/result}"
HEAD_MODE="headed"
MAX_TURN_SEC="45"
CASE_TIMEOUT_SEC="240"
KEEP_STACK=0
TARGET_BOTS=(bot-a bot-b bot-c bot-d bot-e)
COWORK_CASE_LIMIT="${COWORK_CASE_LIMIT:-0}"

TMP_CONFIG_PATH=""
TMP_RUNTIME_DIR=""
SUITE_DIR=""
RAW_DIR=""
RUNNER_LOG=""
STARTED_AT=""
FINISHED_AT=""
PYTHON_BIN=""
MOCK_PORT=""
EMBEDDED_BASE_PORT=""
GATEWAY_PORT=""
BASE_URL=""
INFRA_FAILURE=0

ALLOW_UNSAFE_TIMEOUT=0

usage() {
  cat <<USAGE
Usage: ./scripts/run-cowork-web-10cases.sh [--headed|--headless] [--result-root result] [--max-turn-sec 45] [--case-timeout-sec 240] [--keep-stack] [--allow-unsafe-timeout]
USAGE
}

log() {
  local message="$1"
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$message" | tee -a "$RUNNER_LOG"
}

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required binary: $1" >&2
    exit 2
  fi
}

require_python() {
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    return 0
  fi
  if [[ -x "$ROOT_DIR/.pyshim/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.pyshim/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
    return 0
  fi
  echo "python not found" >&2
  exit 2
}

find_free_port() {
  "$PYTHON_BIN" - "$1" <<'PY'
import socket
import sys
start = int(sys.argv[1])
for port in range(start, start + 400):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
    print(port)
    raise SystemExit(0)
raise SystemExit(1)
PY
}

find_free_port_block() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import socket
import sys
start = int(sys.argv[1])
size = int(sys.argv[2])
for base in range(start, start + 400):
    sockets = []
    ok = True
    for port in range(base, base + size):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            ok = False
            sock.close()
            break
        sockets.append(sock)
    for sock in sockets:
        sock.close()
    if ok:
        print(base)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

health_ok() {
  curl -fsS "$1/healthz" >/dev/null 2>&1
}

create_temp_config() {
  "$PYTHON_BIN" - "$SOURCE_CONFIG_PATH" "$TMP_CONFIG_PATH" "${TARGET_BOTS[@]}" <<'PY'
from pathlib import Path
import sys
import yaml

source = Path(sys.argv[1]).expanduser().resolve()
target = Path(sys.argv[2]).expanduser().resolve()
allowed = sys.argv[3:]
payload = yaml.safe_load(source.read_text(encoding='utf-8')) or {}
bots = payload.get('bots') if isinstance(payload, dict) else []
if not isinstance(bots, list):
    bots = []
filtered = [row for row in bots if isinstance(row, dict) and str(row.get('bot_id') or '') in allowed]
missing = [bot_id for bot_id in allowed if not any(str(row.get('bot_id') or '') == bot_id for row in filtered)]
if missing:
    raise SystemExit(f'missing required bots in source config: {", ".join(missing)}')
filtered.sort(key=lambda row: allowed.index(str(row.get('bot_id') or '')))
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(yaml.safe_dump({'bots': filtered}, sort_keys=False, allow_unicode=True), encoding='utf-8')
PY
}

cleanup() {
  if [[ "$KEEP_STACK" -eq 0 ]]; then
    if [[ -n "$TMP_CONFIG_PATH" && -n "$TMP_RUNTIME_DIR" ]]; then
      CONFIG_PATH="$TMP_CONFIG_PATH" \
      RUNTIME_DIR="$TMP_RUNTIME_DIR/runlogs" \
      MOCK_DATA_DIR="$TMP_RUNTIME_DIR/mock-data" \
      MOCK_DB_PATH="$TMP_RUNTIME_DIR/mock-data/mock_messenger.db" \
      MOCK_PORT="$MOCK_PORT" \
      EMBEDDED_BASE_PORT="$EMBEDDED_BASE_PORT" \
      GATEWAY_PORT="$GATEWAY_PORT" \
      "$RUNNER" stop >>"$RUNNER_LOG" 2>&1 || true
    fi
    [[ -n "$TMP_CONFIG_PATH" ]] && rm -f "$TMP_CONFIG_PATH"
    [[ -n "$TMP_RUNTIME_DIR" ]] && rm -rf "$TMP_RUNTIME_DIR"
  fi
}

start_stack() {
  log "starting isolated multibot stack"
  CONFIG_PATH="$TMP_CONFIG_PATH" \
  RUNTIME_DIR="$TMP_RUNTIME_DIR/runlogs" \
  MOCK_DATA_DIR="$TMP_RUNTIME_DIR/mock-data" \
  MOCK_DB_PATH="$TMP_RUNTIME_DIR/mock-data/mock_messenger.db" \
  MOCK_PORT="$MOCK_PORT" \
  EMBEDDED_BASE_PORT="$EMBEDDED_BASE_PORT" \
  GATEWAY_PORT="$GATEWAY_PORT" \
  "$RUNNER" start >>"$RUNNER_LOG" 2>&1
  if ! health_ok "$BASE_URL"; then
    log "stack health check failed after start"
    return 1
  fi
  log "stack healthy at $BASE_URL"
}

restart_stack() {
  log "restarting isolated multibot stack"
  CONFIG_PATH="$TMP_CONFIG_PATH" \
  RUNTIME_DIR="$TMP_RUNTIME_DIR/runlogs" \
  MOCK_DATA_DIR="$TMP_RUNTIME_DIR/mock-data" \
  MOCK_DB_PATH="$TMP_RUNTIME_DIR/mock-data/mock_messenger.db" \
  MOCK_PORT="$MOCK_PORT" \
  EMBEDDED_BASE_PORT="$EMBEDDED_BASE_PORT" \
  GATEWAY_PORT="$GATEWAY_PORT" \
  "$RUNNER" stop >>"$RUNNER_LOG" 2>&1 || true
  start_stack
}

ensure_e2e_deps() {
  log "ensuring playwright dependencies"
  pushd tests/e2e >/dev/null
  if [[ ! -d node_modules ]]; then
    npm install >>"$RUNNER_LOG" 2>&1
  fi
  npx playwright install chromium >>"$RUNNER_LOG" 2>&1
  popd >/dev/null
}

preflight_stack() {
  log "running stack preflight"
  local catalog_json
  catalog_json="$(curl -fsS "$BASE_URL/_mock/bot_catalog")"
  for bot_id in "${TARGET_BOTS[@]}"; do
    if ! printf '%s' "$catalog_json" | jq -e --arg bot_id "$bot_id" '.result.bots[] | select(.bot_id == $bot_id)' >/dev/null; then
      log "preflight failed: missing bot $bot_id"
      return 1
    fi
    local mode token
    mode="$(printf '%s' "$catalog_json" | jq -r --arg bot_id "$bot_id" '.result.bots[] | select(.bot_id == $bot_id) | .mode')"
    token="$(printf '%s' "$catalog_json" | jq -r --arg bot_id "$bot_id" '.result.bots[] | select(.bot_id == $bot_id) | .token')"
    if [[ "$mode" != "embedded" ]]; then
      log "preflight failed: bot $bot_id mode=$mode"
      return 1
    fi
    curl -fsS "$BASE_URL/_mock/bot_diagnostics?bot_id=$bot_id&token=$token" >/dev/null
  done
  curl -fsS "$BASE_URL/_mock/control_tower" >/dev/null
  log "stack preflight passed"
}

case_count() {
  jq length "$EFFECTIVE_FIXTURE_PATH"
}

run_case() {
  local case_no="$1"
  local playwright_exit=0
  log "running case $case_no"
  pushd tests/e2e >/dev/null
  set +e
  MOCK_UI_BASE_URL="$BASE_URL" \
  PW_MANUAL_TRACE="1" \
  COWORK_LIVE_RAW_DIR="$RAW_DIR" \
  COWORK_LIVE_CASE_NO="$case_no" \
  COWORK_CASE_TIMEOUT_SEC="$CASE_TIMEOUT_SEC" \
  COWORK_ALLOW_UNSAFE_TIMEOUT="$ALLOW_UNSAFE_TIMEOUT" \
  npx playwright test tests/cowork-web-live-suite.spec.js $( [[ "$HEAD_MODE" == "headed" ]] && printf -- '--headed' || printf '' ) >>"$RUNNER_LOG" 2>&1
  playwright_exit=$?
  set -e
  popd >/dev/null
  if [[ "$playwright_exit" -ne 0 ]]; then
    log "playwright infra failure on case $case_no (exit=$playwright_exit)"
    INFRA_FAILURE=1
    return 1
  fi
  log "case $case_no finished"
  return 0
}

ensure_active_cleared() {
  local active_json cowork_id status_json status
  active_json="$(curl -fsS "$BASE_URL/_mock/cowork/active" || true)"
  cowork_id="$(printf '%s' "$active_json" | jq -r '.result.cowork_id // empty' 2>/dev/null || true)"
  if [[ -z "$cowork_id" ]]; then
    return 0
  fi
  log "active cowork remains after case: $cowork_id"
  curl -fsS -X POST "$BASE_URL/_mock/cowork/$cowork_id/stop" >/dev/null 2>&1 || true
  sleep 2
  status_json="$(curl -fsS "$BASE_URL/_mock/cowork/$cowork_id" || true)"
  status="$(printf '%s' "$status_json" | jq -r '.result.status // empty' 2>/dev/null || true)"
  if [[ "$status" != "completed" && "$status" != "failed" && "$status" != "stopped" ]]; then
    log "cowork still active after stop request; stack restart required"
    restart_stack || return 1
    preflight_stack || return 1
  fi
}

aggregate_reports() {
  FINISHED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  log "aggregating suite report"
  "$PYTHON_BIN" "$ROOT_DIR/scripts/report_cowork_web_suite.py" \
    --suite-dir "$SUITE_DIR" \
    --raw-dir "$RAW_DIR" \
    --fixture-path "$EFFECTIVE_FIXTURE_PATH" \
    --base-url "$BASE_URL" \
    --max-turn-sec "$MAX_TURN_SEC" \
    --case-timeout-sec "$CASE_TIMEOUT_SEC" \
    --mock-port "$MOCK_PORT" \
    --embedded-base-port "$EMBEDDED_BASE_PORT" \
    --gateway-port "$GATEWAY_PORT" \
    --started-at "$STARTED_AT" \
    --finished-at "$FINISHED_AT" \
    $( [[ "$HEAD_MODE" == "headed" ]] && printf -- '--headed ' ) \
    --selected-bots "${TARGET_BOTS[@]}" >>"$RUNNER_LOG" 2>&1
}

final_exit_code() {
  if [[ "$INFRA_FAILURE" -ne 0 ]]; then
    return 2
  fi
  "$PYTHON_BIN" - "$SUITE_DIR/report.json" <<'PY'
import json
import sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
results = report.get('results') or []
all_ok = True
for row in results:
    status = str(row.get('status') or '')
    completion = str(row.get('completion_status') or '').lower()
    if status != 'completed' or completion != 'passed':
        all_ok = False
        break
raise SystemExit(0 if all_ok else 1)
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --headed)
      HEAD_MODE="headed"
      ;;
    --headless)
      HEAD_MODE="headless"
      ;;
    --result-root)
      RESULT_ROOT="$2"
      shift
      ;;
    --max-turn-sec)
      MAX_TURN_SEC="$2"
      shift
      ;;
    --case-timeout-sec)
      CASE_TIMEOUT_SEC="$2"
      shift
      ;;
    --allow-unsafe-timeout)
      ALLOW_UNSAFE_TIMEOUT=1
      ;;
    --keep-stack)
      KEEP_STACK=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

require_bin curl
require_bin jq
require_bin node
require_bin npm
require_bin npx
require_bin mktemp
require_python

STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
SUITE_DIR="$RESULT_ROOT/cowork_web_test_10cases_live_$(date '+%Y%m%d_%H%M%S')"
RAW_DIR="$SUITE_DIR/.raw"
mkdir -p "$SUITE_DIR" "$RAW_DIR"
RUNNER_LOG="$SUITE_DIR/runner.log"
touch "$RUNNER_LOG"
EFFECTIVE_FIXTURE_PATH="$FIXTURE_PATH"

trap cleanup EXIT

TMP_CONFIG_PATH="$(mktemp -t bots-multibot-live-10cases.XXXXXX.yaml)"
TMP_RUNTIME_DIR="$(mktemp -d -t mock-multibot-live-10cases.XXXXXX)"
create_temp_config

MOCK_PORT="$(find_free_port 9182)"
EMBEDDED_BASE_PORT="$(find_free_port_block 8700 5)"
GATEWAY_PORT="$(find_free_port 4412)"
BASE_URL="http://127.0.0.1:$MOCK_PORT"

ensure_e2e_deps
start_stack || exit 2
preflight_stack || exit 2

TOTAL_CASES="$(case_count)"
if [[ "$COWORK_CASE_LIMIT" =~ ^[0-9]+$ ]] && [[ "$COWORK_CASE_LIMIT" -gt 0 ]] && [[ "$COWORK_CASE_LIMIT" -lt "$TOTAL_CASES" ]]; then
  TOTAL_CASES="$COWORK_CASE_LIMIT"
  EFFECTIVE_FIXTURE_PATH="$TMP_RUNTIME_DIR/cowork_web_10cases.partial.json"
  jq ".[0:$TOTAL_CASES]" "$FIXTURE_PATH" > "$EFFECTIVE_FIXTURE_PATH"
fi

log "suite start: total_cases=$TOTAL_CASES mode=$HEAD_MODE base=$BASE_URL"

for case_no in $(seq 1 "$TOTAL_CASES"); do
  if ! run_case "$case_no"; then
    ensure_active_cleared || true
    continue
  fi
  ensure_active_cleared || true
done

aggregate_reports || exit 2
if final_exit_code; then
  log "suite completed: all cases passed"
  exit 0
fi
log "suite completed with failures or rework"
exit 1
