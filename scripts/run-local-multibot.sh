#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="$ROOT_DIR/$VENV_DIR/bin/python"
SCRIPT_NAME="${RUN_LOCAL_MULTIBOT_ALIAS:-$0}"

CONFIG_PATH="${CONFIG_PATH:-config/bots.multibot.yaml}"
MAX_BOTS="${MAX_BOTS:-8}"
MOCK_HOST="${MOCK_HOST:-127.0.0.1}"
MOCK_PORT="${MOCK_PORT:-9082}"
MOCK_DB_PATH="${MOCK_DB_PATH:-$ROOT_DIR/.mock_messenger_9082/mock_messenger.db}"
MOCK_DATA_DIR="${MOCK_DATA_DIR:-$ROOT_DIR/.mock_messenger_9082}"

EMBEDDED_HOST="${EMBEDDED_HOST:-127.0.0.1}"
EMBEDDED_BASE_PORT="${EMBEDDED_BASE_PORT:-8600}"
GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_PORT="${GATEWAY_PORT:-4312}"

RUNTIME_DIR="${RUNTIME_DIR:-$ROOT_DIR/.runlogs/local-multibot}"
PID_MOCK_FILE="$RUNTIME_DIR/mock.pid"
PID_SUPERVISOR_FILE="$RUNTIME_DIR/supervisor.pid"
MOCK_OUT_LOG="$RUNTIME_DIR/mock.out.log"
MOCK_ERR_LOG="$RUNTIME_DIR/mock.err.log"
SUP_OUT_LOG="$RUNTIME_DIR/supervisor.out.log"
SUP_ERR_LOG="$RUNTIME_DIR/supervisor.err.log"
EFFECTIVE_CONFIG_PATH="$CONFIG_PATH"
SOURCE_BOT_COUNT=0
EFFECTIVE_BOT_COUNT=0

usage() {
  cat <<USAGE
Usage: $SCRIPT_NAME [up|start|stop|restart|status|logs|doctor]

Environment overrides:
  CONFIG_PATH, MOCK_HOST, MOCK_PORT, EMBEDDED_HOST, EMBEDDED_BASE_PORT,
  GATEWAY_HOST, GATEWAY_PORT, VENV_DIR, RUNTIME_DIR, MAX_BOTS
USAGE
}

require_python() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "venv python not found: $PYTHON_BIN" >&2
    exit 1
  fi
}

ensure_dirs() {
  mkdir -p "$RUNTIME_DIR" "$MOCK_DATA_DIR" "$(dirname "$MOCK_DB_PATH")"
}

pid_from_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    tr -d ' \t\r\n' <"$file"
  fi
}

pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

pid_command() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null || true
}

is_mock_command() {
  local cmd="$1"
  [[ "$cmd" == *"telegram_bot_new.mock_messenger.main"* ]] \
    && [[ "$cmd" == *"--port $MOCK_PORT"* ]] \
    && [[ "$cmd" == *"--bots-config $EFFECTIVE_CONFIG_PATH"* ]]
}

is_supervisor_command() {
  local cmd="$1"
  [[ "$cmd" == *"telegram_bot_new.main supervisor"* ]] && [[ "$cmd" == *"--config $EFFECTIVE_CONFIG_PATH"* ]]
}

health_ok() {
  local url="$1"
  curl -fsS "$url" >/dev/null 2>&1
}

listener_pid() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | head -n 1 || true
}

stop_pid() {
  local pid="$1"
  local name="$2"
  if ! pid_alive "$pid"; then
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do
    if ! pid_alive "$pid"; then
      return 0
    fi
    sleep 0.2
  done
  echo "force killing $name pid=$pid"
  kill -9 "$pid" 2>/dev/null || true
}

wait_http_ok() {
  local url="$1"
  local tries="${2:-40}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

spawn_detached() {
  local out_log="$1"
  local err_log="$2"
  shift 2
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" >"$out_log" 2>"$err_log" < /dev/null &
  else
    nohup "$@" >"$out_log" 2>"$err_log" < /dev/null &
  fi
  echo $!
}

prepare_effective_config() {
  local target_path result
  target_path="$RUNTIME_DIR/bots.effective.yaml"
  result="$("$PYTHON_BIN" - "$ROOT_DIR" "$CONFIG_PATH" "$target_path" "$MAX_BOTS" <<'PY'
import sys
from pathlib import Path
import re

import yaml

root_dir = Path(sys.argv[1]).expanduser().resolve()
config_arg = Path(sys.argv[2]).expanduser()
if not config_arg.is_absolute():
    config_arg = (root_dir / config_arg).resolve()
source_path = config_arg
target_path = Path(sys.argv[3]).expanduser().resolve()
max_bots_raw = str(sys.argv[4]).strip()

try:
    max_bots = int(max_bots_raw)
except Exception:
    max_bots = 8

raw = {}
if source_path.exists():
    loaded = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        raw = loaded

bots = raw.get("bots")
if not isinstance(bots, list):
    bots = []

source_count = len(bots)
if max_bots > 0:
    effective_bots = bots[:max_bots]
else:
    effective_bots = bots

# Local multi-bot runtime: enforce per-bot physical DB isolation by default.
state_dir = target_path.parent / "state"
state_dir.mkdir(parents=True, exist_ok=True)
for idx, bot in enumerate(effective_bots, start=1):
    if not isinstance(bot, dict):
        continue
    raw_bot_id = str(bot.get("bot_id") or f"bot-{idx}").strip() or f"bot-{idx}"
    safe_bot_id = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_bot_id) or f"bot-{idx}"
    if not str(bot.get("database_url") or "").strip():
        db_path = (state_dir / f"{safe_bot_id}.db").resolve()
        bot["database_url"] = f"sqlite+aiosqlite:///{db_path}"

target_path.parent.mkdir(parents=True, exist_ok=True)
target_path.write_text(
    yaml.safe_dump({"bots": effective_bots}, sort_keys=False, allow_unicode=True),
    encoding="utf-8",
)

print(target_path)
print(source_count)
print(len(effective_bots))
PY
)"

  EFFECTIVE_CONFIG_PATH="$(echo "$result" | sed -n '1p')"
  SOURCE_BOT_COUNT="$(echo "$result" | sed -n '2p')"
  EFFECTIVE_BOT_COUNT="$(echo "$result" | sed -n '3p')"
}

embedded_urls() {
  "$PYTHON_BIN" - "$EFFECTIVE_CONFIG_PATH" "$EMBEDDED_HOST" "$EMBEDDED_BASE_PORT" <<'PY'
import sys
from pathlib import Path
from telegram_bot_new.settings import get_global_settings, load_bots_config

config_path = Path(sys.argv[1]).expanduser().resolve()
host = sys.argv[2]
base_port = int(sys.argv[3])

try:
    bots = load_bots_config(config_path, get_global_settings(), allow_env_fallback=False)
except Exception:
    raise SystemExit(0)

embedded_idx = 0
for bot in bots:
    if bot.mode != "embedded":
        continue
    print(f"{bot.bot_id}=http://{host}:{base_port + embedded_idx}")
    embedded_idx += 1
PY
}

ensure_embedded_ports_free() {
  while IFS='=' read -r bot_id url; do
    [[ -z "$bot_id" ]] && continue
    local port listener cmd
    port="${url##*:}"
    listener="$(listener_pid "$port")"
    if [[ -n "$listener" ]]; then
      cmd="$(pid_command "$listener")"
      echo "embedded port $port for $bot_id is already in use (pid=$listener)." >&2
      echo "command: $cmd" >&2
      echo "stop existing stack first, then retry." >&2
      exit 1
    fi
  done < <(embedded_urls)
}

start_mock() {
  local existing listener cmd pid
  existing="$(pid_from_file "$PID_MOCK_FILE")"
  if pid_alive "$existing"; then
    cmd="$(pid_command "$existing")"
    if is_mock_command "$cmd" && health_ok "http://$MOCK_HOST:$MOCK_PORT/healthz"; then
      echo "mock already running (pid=$existing)"
      return 0
    fi
    echo "stale mock pid detected (pid=$existing). restarting mock."
    stop_pid "$existing" "mock(stale)"
    rm -f "$PID_MOCK_FILE"
  fi

  listener="$(listener_pid "$MOCK_PORT")"
  if [[ -n "$listener" ]]; then
    cmd="$(pid_command "$listener")"
    if is_mock_command "$cmd"; then
      echo "$listener" >"$PID_MOCK_FILE"
      echo "mock already listening on :$MOCK_PORT (pid=$listener), reusing."
      return 0
    fi
    echo "port $MOCK_PORT already in use by another process: $cmd" >&2
    exit 1
  fi

  pid="$(spawn_detached "$MOCK_OUT_LOG" "$MOCK_ERR_LOG" \
    "$PYTHON_BIN" -m telegram_bot_new.mock_messenger.main \
    --host "$MOCK_HOST" \
    --port "$MOCK_PORT" \
    --db-path "$MOCK_DB_PATH" \
    --data-dir "$MOCK_DATA_DIR" \
    --bots-config "$EFFECTIVE_CONFIG_PATH" \
    --embedded-host "$EMBEDDED_HOST" \
    --embedded-base-port "$EMBEDDED_BASE_PORT")"
  echo "$pid" >"$PID_MOCK_FILE"

  if ! wait_http_ok "http://$MOCK_HOST:$MOCK_PORT/healthz" 60; then
    echo "mock failed to start. see: $MOCK_ERR_LOG" >&2
    return 1
  fi
  pid="$(listener_pid "$MOCK_PORT")"
  if [[ -n "$pid" ]]; then
    echo "$pid" >"$PID_MOCK_FILE"
  fi
  echo "mock started (pid=$pid) at http://$MOCK_HOST:$MOCK_PORT"
}

start_supervisor() {
  local existing pid cmd
  existing="$(pid_from_file "$PID_SUPERVISOR_FILE")"
  if pid_alive "$existing"; then
    cmd="$(pid_command "$existing")"
    if is_supervisor_command "$cmd"; then
      echo "supervisor already running (pid=$existing)"
      return 0
    fi
    echo "stale supervisor pid detected (pid=$existing). restarting supervisor."
    stop_pid "$existing" "supervisor(stale)"
    rm -f "$PID_SUPERVISOR_FILE"
  fi

  ensure_embedded_ports_free

  pid="$(spawn_detached "$SUP_OUT_LOG" "$SUP_ERR_LOG" \
    env TELEGRAM_API_BASE_URL="http://$MOCK_HOST:$MOCK_PORT" STRICT_BOT_DB_ISOLATION=1 PYTHONUNBUFFERED=1 \
    "$PYTHON_BIN" -m telegram_bot_new.main supervisor \
      --config "$EFFECTIVE_CONFIG_PATH" \
      --embedded-host "$EMBEDDED_HOST" \
      --embedded-base-port "$EMBEDDED_BASE_PORT" \
      --gateway-host "$GATEWAY_HOST" \
      --gateway-port "$GATEWAY_PORT")"
  sleep 1
  pid="$(pgrep -f "telegram_bot_new.main supervisor --config $EFFECTIVE_CONFIG_PATH" | head -n 1 || true)"
  if [[ -z "$pid" ]] || ! pid_alive "$pid"; then
    echo "supervisor failed to start. see: $SUP_ERR_LOG" >&2
    return 1
  fi
  echo "$pid" >"$PID_SUPERVISOR_FILE"
  echo "supervisor started (pid=$pid)"
}

show_urls() {
  echo ""
  echo "UI:      http://$MOCK_HOST:$MOCK_PORT/_mock/ui"
  echo "Mock:    http://$MOCK_HOST:$MOCK_PORT/healthz"
  if [[ "${SOURCE_BOT_COUNT:-0}" -gt "${EFFECTIVE_BOT_COUNT:-0}" ]]; then
    echo "Bots:    limited to ${EFFECTIVE_BOT_COUNT}/${SOURCE_BOT_COUNT} (MAX_BOTS=${MAX_BOTS})"
  else
    echo "Bots:    ${EFFECTIVE_BOT_COUNT:-0}"
  fi
  echo "Config:  $EFFECTIVE_CONFIG_PATH"
  while IFS='=' read -r bot_id url; do
    [[ -z "$bot_id" ]] && continue
    echo "${bot_id}: ${url}/healthz"
  done < <(embedded_urls)
  echo "Status:  $SCRIPT_NAME status"
  echo "Logs:    $SCRIPT_NAME logs"
  echo "Stop:    $SCRIPT_NAME stop"
}

do_start() {
  require_python
  ensure_dirs
  prepare_effective_config
  start_mock
  start_supervisor
  show_urls
}

do_up() {
  require_python
  ensure_dirs
  prepare_effective_config
  local started_mock_by_up=0
  local mock_pid

  mock_pid="$(listener_pid "$MOCK_PORT")"
  if [[ -z "$mock_pid" ]]; then
    "$PYTHON_BIN" -m telegram_bot_new.mock_messenger.main \
      --host "$MOCK_HOST" \
      --port "$MOCK_PORT" \
      --db-path "$MOCK_DB_PATH" \
      --data-dir "$MOCK_DATA_DIR" \
      --bots-config "$EFFECTIVE_CONFIG_PATH" \
      --embedded-host "$EMBEDDED_HOST" \
      --embedded-base-port "$EMBEDDED_BASE_PORT" \
      >"$MOCK_OUT_LOG" 2>"$MOCK_ERR_LOG" &
    mock_pid=$!
    echo "$mock_pid" >"$PID_MOCK_FILE"
    started_mock_by_up=1
    wait_http_ok "http://$MOCK_HOST:$MOCK_PORT/healthz" 60 || {
      echo "mock failed to start. see: $MOCK_ERR_LOG" >&2
      exit 1
    }
  else
    echo "$mock_pid" >"$PID_MOCK_FILE"
    echo "mock already listening on :$MOCK_PORT (pid=$mock_pid), reusing."
  fi

  ensure_embedded_ports_free

  echo ""
  echo "UI:      http://$MOCK_HOST:$MOCK_PORT/_mock/ui"
  echo "Mode:    foreground supervisor (Ctrl+C to stop)"
  if [[ "${SOURCE_BOT_COUNT:-0}" -gt "${EFFECTIVE_BOT_COUNT:-0}" ]]; then
    echo "Bots:    limited to ${EFFECTIVE_BOT_COUNT}/${SOURCE_BOT_COUNT} (MAX_BOTS=${MAX_BOTS})"
  else
    echo "Bots:    ${EFFECTIVE_BOT_COUNT:-0}"
  fi
  echo "Config:  $EFFECTIVE_CONFIG_PATH"
  echo ""

  cleanup_up() {
    if [[ "${started_mock_by_up:-0}" -eq 1 ]]; then
      stop_pid "${mock_pid:-}" "mock"
      rm -f "$PID_MOCK_FILE"
    fi
    rm -f "$PID_SUPERVISOR_FILE"
  }
  trap cleanup_up EXIT INT TERM

  TELEGRAM_API_BASE_URL="http://$MOCK_HOST:$MOCK_PORT" \
  PYTHONUNBUFFERED=1 \
  "$PYTHON_BIN" -m telegram_bot_new.main supervisor \
    --config "$EFFECTIVE_CONFIG_PATH" \
    --embedded-host "$EMBEDDED_HOST" \
    --embedded-base-port "$EMBEDDED_BASE_PORT" \
    --gateway-host "$GATEWAY_HOST" \
    --gateway-port "$GATEWAY_PORT"
}

do_stop() {
  require_python
  ensure_dirs
  prepare_effective_config
  local sup_pid mock_pid
  sup_pid="$(pid_from_file "$PID_SUPERVISOR_FILE")"
  mock_pid="$(pid_from_file "$PID_MOCK_FILE")"

  if ! pid_alive "$sup_pid"; then
    sup_pid="$(pgrep -f "telegram_bot_new.main supervisor --config $EFFECTIVE_CONFIG_PATH" | head -n 1 || true)"
  fi
  if ! pid_alive "$mock_pid"; then
    mock_pid="$(listener_pid "$MOCK_PORT")"
  fi

  stop_pid "$sup_pid" "supervisor"
  stop_pid "$mock_pid" "mock"
  rm -f "$PID_SUPERVISOR_FILE" "$PID_MOCK_FILE"
  echo "stopped local-multibot stack"
}

do_status() {
  require_python
  ensure_dirs
  prepare_effective_config
  local sup_pid mock_pid cmd
  sup_pid="$(pid_from_file "$PID_SUPERVISOR_FILE")"
  mock_pid="$(pid_from_file "$PID_MOCK_FILE")"

  if ! pid_alive "$sup_pid"; then
    sup_pid="$(pgrep -f "telegram_bot_new.main supervisor --config $EFFECTIVE_CONFIG_PATH" | head -n 1 || true)"
    if [[ -n "$sup_pid" ]]; then
      echo "$sup_pid" >"$PID_SUPERVISOR_FILE"
    fi
  fi
  if ! pid_alive "$mock_pid"; then
    mock_pid="$(listener_pid "$MOCK_PORT")"
    if [[ -n "$mock_pid" ]]; then
      cmd="$(pid_command "$mock_pid")"
      if ! is_mock_command "$cmd"; then
        mock_pid=""
      fi
    fi
    if [[ -n "$mock_pid" ]]; then
      echo "$mock_pid" >"$PID_MOCK_FILE"
    fi
  fi

  echo "supervisor_pid_file=${sup_pid:-none}"
  if pid_alive "$sup_pid"; then
    cmd="$(pid_command "$sup_pid")"
    if is_supervisor_command "$cmd"; then
      echo "supervisor_alive=yes"
      echo "supervisor_cmd=$cmd"
    else
      echo "supervisor_alive=no"
    fi
  else
    echo "supervisor_alive=no"
  fi

  echo "mock_pid_file=${mock_pid:-none}"
  if pid_alive "$mock_pid"; then
    cmd="$(pid_command "$mock_pid")"
    if is_mock_command "$cmd"; then
      echo "mock_alive=yes"
      echo "mock_cmd=$cmd"
    else
      echo "mock_alive=no"
    fi
  else
    echo "mock_alive=no"
  fi

  echo "mock_health=$(curl -fsS "http://$MOCK_HOST:$MOCK_PORT/healthz" 2>/dev/null || echo down)"
  while IFS='=' read -r bot_id url; do
    [[ -z "$bot_id" ]] && continue
    echo "${bot_id}_health=$(curl -fsS "$url/healthz" 2>/dev/null || echo down)"
  done < <(embedded_urls)
}

do_logs() {
  ensure_dirs
  touch "$MOCK_OUT_LOG" "$MOCK_ERR_LOG" "$SUP_OUT_LOG" "$SUP_ERR_LOG"
  tail -n 80 -f "$MOCK_OUT_LOG" "$MOCK_ERR_LOG" "$SUP_OUT_LOG" "$SUP_ERR_LOG"
}

do_doctor() {
  require_python
  ensure_dirs
  prepare_effective_config
  echo "python=$PYTHON_BIN"
  echo "config=$EFFECTIVE_CONFIG_PATH"
  echo "effective_bots=${EFFECTIVE_BOT_COUNT:-0}"
  echo "source_bots=${SOURCE_BOT_COUNT:-0}"
  echo "mock_listener=$(listener_pid "$MOCK_PORT")"
  echo "mock_health=$(curl -fsS "http://$MOCK_HOST:$MOCK_PORT/healthz" 2>/dev/null || echo down)"

  while IFS='=' read -r bot_id url; do
    [[ -z "$bot_id" ]] && continue
    local port
    port="${url##*:}"
    echo "${bot_id}_listener=$(listener_pid "$port")"
    echo "${bot_id}_health=$(curl -fsS "$url/healthz" 2>/dev/null || echo down)"
  done < <(embedded_urls)
}

CMD="${1:-up}"
case "$CMD" in
  up)
    do_up
    ;;
  start)
    do_start
    ;;
  stop)
    do_stop
    ;;
  restart)
    do_stop
    do_start
    ;;
  status)
    do_status
    ;;
  logs)
    do_logs
    ;;
  doctor)
    do_doctor
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "unknown command: $CMD" >&2
    usage
    exit 1
    ;;
esac
