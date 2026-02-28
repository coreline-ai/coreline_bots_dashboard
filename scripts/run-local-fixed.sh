#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="$ROOT_DIR/$VENV_DIR/bin/python"
SCRIPT_NAME="${RUN_LOCAL_ALIAS:-$0}"

CONFIG_PATH="${CONFIG_PATH:-config/bots.yaml}"
BOT_ID="${BOT_ID:-bot-1}"

MOCK_HOST="${MOCK_HOST:-127.0.0.1}"
MOCK_PORT="${MOCK_PORT:-9082}"
MOCK_DB_PATH="${MOCK_DB_PATH:-$ROOT_DIR/.mock_messenger_9082/mock_messenger.db}"
MOCK_DATA_DIR="${MOCK_DATA_DIR:-$ROOT_DIR/.mock_messenger_9082}"

BOT_HOST="${BOT_HOST:-127.0.0.1}"
BOT_PORT="${BOT_PORT:-8600}"
VIRTUAL_TOKEN="${TELEGRAM_VIRTUAL_TOKEN:-mock_token_1}"

RUNTIME_DIR="${RUNTIME_DIR:-$ROOT_DIR/.runlogs/local-fixed}"
PID_MOCK_FILE="$RUNTIME_DIR/mock.pid"
PID_BOT_FILE="$RUNTIME_DIR/bot.pid"
MOCK_OUT_LOG="$RUNTIME_DIR/mock.out.log"
MOCK_ERR_LOG="$RUNTIME_DIR/mock.err.log"
BOT_OUT_LOG="$RUNTIME_DIR/bot.out.log"
BOT_ERR_LOG="$RUNTIME_DIR/bot.err.log"

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [up|start|stop|restart|status|logs|doctor]

Environment overrides:
  BOT_ID, CONFIG_PATH, MOCK_HOST, MOCK_PORT, BOT_HOST, BOT_PORT,
  TELEGRAM_VIRTUAL_TOKEN, VENV_DIR, RUNTIME_DIR
EOF
}

require_python() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "venv python not found: $PYTHON_BIN" >&2
    echo "Run setup first (create .venv and install project)." >&2
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
  local tries="${2:-50}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

ensure_detached_stable() {
  local tries="${1:-15}"
  for _ in $(seq 1 "$tries"); do
    local mock_pid bot_pid
    mock_pid="$(pid_from_file "$PID_MOCK_FILE")"
    bot_pid="$(pid_from_file "$PID_BOT_FILE")"
    if pid_alive "$mock_pid" && pid_alive "$bot_pid"; then
      if curl -fsS "http://$MOCK_HOST:$MOCK_PORT/healthz" >/dev/null 2>&1 && \
         curl -fsS "http://$BOT_HOST:$BOT_PORT/healthz" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 0.2
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

expect_or_reuse_listener() {
  local port="$1"
  local expected_pattern="$2"
  local known_pid_file="$3"
  local name="$4"

  local pid
  pid="$(listener_pid "$port")"
  if [[ -z "$pid" ]]; then
    return 0
  fi

  local cmd
  cmd="$(pid_command "$pid")"
  if [[ "$cmd" =~ $expected_pattern ]]; then
    echo "$pid" >"$known_pid_file"
    echo "$name already listening on :$port (pid=$pid), reusing."
    return 0
  fi

  echo "port $port is already in use by another process (pid=$pid)." >&2
  echo "command: $cmd" >&2
  echo "Stop that process first, then retry." >&2
  exit 1
}

start_mock() {
  local existing
  existing="$(pid_from_file "$PID_MOCK_FILE")"
  if pid_alive "$existing"; then
    echo "mock already running (pid=$existing)"
    return 0
  fi
  expect_or_reuse_listener "$MOCK_PORT" "telegram_bot_new\\.mock_messenger\\.main.*--port $MOCK_PORT" "$PID_MOCK_FILE" "mock"
  existing="$(pid_from_file "$PID_MOCK_FILE")"
  if pid_alive "$existing"; then
    return 0
  fi

  local pid
  pid="$(spawn_detached "$MOCK_OUT_LOG" "$MOCK_ERR_LOG" \
    "$PYTHON_BIN" -m telegram_bot_new.mock_messenger.main \
    --host "$MOCK_HOST" \
    --port "$MOCK_PORT" \
    --db-path "$MOCK_DB_PATH" \
    --data-dir "$MOCK_DATA_DIR")"
  echo "$pid" >"$PID_MOCK_FILE"

  if ! wait_http_ok "http://$MOCK_HOST:$MOCK_PORT/healthz" 80; then
    echo "mock failed to start. see: $MOCK_ERR_LOG" >&2
    return 1
  fi
  echo "mock started (pid=$pid) at http://$MOCK_HOST:$MOCK_PORT"
}

start_bot() {
  local existing
  existing="$(pid_from_file "$PID_BOT_FILE")"
  if pid_alive "$existing"; then
    echo "bot already running (pid=$existing)"
    return 0
  fi
  expect_or_reuse_listener "$BOT_PORT" "telegram_bot_new\\.main run-bot.*--bot-id $BOT_ID.*--embedded-port $BOT_PORT" "$PID_BOT_FILE" "bot"
  existing="$(pid_from_file "$PID_BOT_FILE")"
  if pid_alive "$existing"; then
    return 0
  fi

  local pid
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid env \
      TELEGRAM_API_BASE_URL="http://$MOCK_HOST:$MOCK_PORT" \
      TELEGRAM_VIRTUAL_TOKEN="$VIRTUAL_TOKEN" \
      PYTHONUNBUFFERED=1 \
      "$PYTHON_BIN" -m telegram_bot_new.main run-bot \
      --config "$CONFIG_PATH" \
      --bot-id "$BOT_ID" \
      --embedded-host "$BOT_HOST" \
      --embedded-port "$BOT_PORT" \
      >"$BOT_OUT_LOG" 2>"$BOT_ERR_LOG" < /dev/null &
  else
    nohup env \
      TELEGRAM_API_BASE_URL="http://$MOCK_HOST:$MOCK_PORT" \
      TELEGRAM_VIRTUAL_TOKEN="$VIRTUAL_TOKEN" \
      PYTHONUNBUFFERED=1 \
      "$PYTHON_BIN" -m telegram_bot_new.main run-bot \
      --config "$CONFIG_PATH" \
      --bot-id "$BOT_ID" \
      --embedded-host "$BOT_HOST" \
      --embedded-port "$BOT_PORT" \
      >"$BOT_OUT_LOG" 2>"$BOT_ERR_LOG" < /dev/null &
  fi
  pid=$!
  echo "$pid" >"$PID_BOT_FILE"

  if ! wait_http_ok "http://$BOT_HOST:$BOT_PORT/healthz" 80; then
    echo "bot failed to start. see: $BOT_ERR_LOG" >&2
    return 1
  fi
  echo "bot started (pid=$pid) at http://$BOT_HOST:$BOT_PORT"
}

do_start() {
  require_python
  ensure_dirs
  local had_mock_listener had_bot_listener
  local mock_pid bot_pid
  had_mock_listener=0
  had_bot_listener=0
  if [[ -n "$(listener_pid "$MOCK_PORT")" ]]; then
    had_mock_listener=1
  fi
  if [[ -n "$(listener_pid "$BOT_PORT")" ]]; then
    had_bot_listener=1
  fi

  if ! start_mock; then
    return 1
  fi
  if ! start_bot; then
    if [[ "$had_mock_listener" -eq 0 ]]; then
      mock_pid="$(pid_from_file "$PID_MOCK_FILE")"
      stop_pid "$mock_pid" "mock"
      rm -f "$PID_MOCK_FILE"
    fi
    return 1
  fi
  if ! ensure_detached_stable 20; then
    if [[ "$had_bot_listener" -eq 0 ]]; then
      bot_pid="$(pid_from_file "$PID_BOT_FILE")"
      stop_pid "$bot_pid" "bot"
      rm -f "$PID_BOT_FILE"
    fi
    if [[ "$had_mock_listener" -eq 0 ]]; then
      mock_pid="$(pid_from_file "$PID_MOCK_FILE")"
      stop_pid "$mock_pid" "mock"
      rm -f "$PID_MOCK_FILE"
    fi
    echo "detached start was not stable in this environment." >&2
    echo "Use '$SCRIPT_NAME up' (foreground) for reliable local execution." >&2
    echo "See logs:" >&2
    echo "  $MOCK_ERR_LOG" >&2
    echo "  $BOT_ERR_LOG" >&2
    exit 1
  fi
  echo ""
  echo "UI:      http://$MOCK_HOST:$MOCK_PORT/_mock/ui?token=$VIRTUAL_TOKEN&chat_id=1001&user_id=9001"
  echo "Health:  http://$BOT_HOST:$BOT_PORT/healthz"
  echo "Status:  $SCRIPT_NAME status"
  echo "Logs:    $SCRIPT_NAME logs"
  echo "Stop:    $SCRIPT_NAME stop"
}

do_stop() {
  local bot_pid mock_pid
  bot_pid="$(pid_from_file "$PID_BOT_FILE")"
  mock_pid="$(pid_from_file "$PID_MOCK_FILE")"

  if [[ -z "$bot_pid" ]]; then
    local bot_listener_pid bot_listener_cmd
    bot_listener_pid="$(listener_pid "$BOT_PORT")"
    bot_listener_cmd="$(pid_command "$bot_listener_pid")"
    if [[ "$bot_listener_cmd" =~ telegram_bot_new\.main\ run-bot.*--bot-id\ $BOT_ID.*--embedded-port\ $BOT_PORT ]]; then
      bot_pid="$bot_listener_pid"
    fi
  fi

  if [[ -z "$mock_pid" ]]; then
    local mock_listener_pid mock_listener_cmd
    mock_listener_pid="$(listener_pid "$MOCK_PORT")"
    mock_listener_cmd="$(pid_command "$mock_listener_pid")"
    if [[ "$mock_listener_cmd" =~ telegram_bot_new\.mock_messenger\.main.*--port\ $MOCK_PORT ]]; then
      mock_pid="$mock_listener_pid"
    fi
  fi

  stop_pid "$bot_pid" "bot"
  stop_pid "$mock_pid" "mock"
  rm -f "$PID_BOT_FILE" "$PID_MOCK_FILE"
  echo "stopped local-fixed stack"
}

do_status() {
  local mock_pid bot_pid
  mock_pid="$(pid_from_file "$PID_MOCK_FILE")"
  bot_pid="$(pid_from_file "$PID_BOT_FILE")"

  if ! pid_alive "$mock_pid"; then
    local mock_listener_pid mock_listener_cmd
    mock_listener_pid="$(listener_pid "$MOCK_PORT")"
    mock_listener_cmd="$(pid_command "$mock_listener_pid")"
    if [[ "$mock_listener_cmd" =~ telegram_bot_new\.mock_messenger\.main.*--port\ $MOCK_PORT ]]; then
      mock_pid="$mock_listener_pid"
    fi
  fi

  if ! pid_alive "$bot_pid"; then
    local bot_listener_pid bot_listener_cmd
    bot_listener_pid="$(listener_pid "$BOT_PORT")"
    bot_listener_cmd="$(pid_command "$bot_listener_pid")"
    if [[ "$bot_listener_cmd" =~ telegram_bot_new\.main\ run-bot.*--bot-id\ $BOT_ID.*--embedded-port\ $BOT_PORT ]]; then
      bot_pid="$bot_listener_pid"
    fi
  fi

  echo "mock_pid_file=${mock_pid:-none}"
  if pid_alive "$mock_pid"; then
    echo "mock_alive=yes"
    echo "mock_cmd=$(pid_command "$mock_pid")"
  else
    echo "mock_alive=no"
  fi

  echo "bot_pid_file=${bot_pid:-none}"
  if pid_alive "$bot_pid"; then
    echo "bot_alive=yes"
    echo "bot_cmd=$(pid_command "$bot_pid")"
  else
    echo "bot_alive=no"
  fi

  echo "mock_health=$(curl -fsS "http://$MOCK_HOST:$MOCK_PORT/healthz" 2>/dev/null || echo down)"
  echo "bot_health=$(curl -fsS "http://$BOT_HOST:$BOT_PORT/healthz" 2>/dev/null || echo down)"
  if ! pid_alive "$bot_pid"; then
    echo "hint=run '$SCRIPT_NAME up' for stable foreground mode"
  fi
}

do_doctor() {
  require_python
  echo "python=$PYTHON_BIN"
  echo "mock_target=http://$MOCK_HOST:$MOCK_PORT"
  echo "bot_target=http://$BOT_HOST:$BOT_PORT"

  local pid9081 pid9082
  pid9081="$(listener_pid 9081)"
  pid9082="$(listener_pid "$MOCK_PORT")"
  if [[ -n "$pid9081" ]]; then
    echo "port_9081_listener_pid=$pid9081"
    echo "port_9081_listener_cmd=$(pid_command "$pid9081")"
  else
    echo "port_9081_listener=none"
  fi
  if [[ -n "$pid9082" ]]; then
    echo "port_${MOCK_PORT}_listener_pid=$pid9082"
    echo "port_${MOCK_PORT}_listener_cmd=$(pid_command "$pid9082")"
  else
    echo "port_${MOCK_PORT}_listener=none"
  fi

  echo "mock_health=$(curl -fsS "http://$MOCK_HOST:$MOCK_PORT/healthz" 2>/dev/null || echo down)"
  echo "bot_health=$(curl -fsS "http://$BOT_HOST:$BOT_PORT/healthz" 2>/dev/null || echo down)"

  if [[ -f "$ROOT_DIR/.env" ]]; then
    local env_base
    env_base="$(grep -E '^TELEGRAM_API_BASE_URL=' "$ROOT_DIR/.env" | head -n1 | cut -d'=' -f2- || true)"
    if [[ -n "$env_base" ]]; then
      echo "env_TELEGRAM_API_BASE_URL=$env_base"
    else
      echo "env_TELEGRAM_API_BASE_URL=unset"
    fi
  fi
}

do_logs() {
  ensure_dirs
  touch "$MOCK_OUT_LOG" "$MOCK_ERR_LOG" "$BOT_OUT_LOG" "$BOT_ERR_LOG"
  tail -n 40 -f "$MOCK_OUT_LOG" "$MOCK_ERR_LOG" "$BOT_OUT_LOG" "$BOT_ERR_LOG"
}

do_up() {
  require_python
  ensure_dirs

  local started_mock_by_up=0
  local mock_pid bot_pid rc

  mock_pid="$(listener_pid "$MOCK_PORT")"
  if [[ -n "$mock_pid" ]]; then
    local mock_cmd
    mock_cmd="$(pid_command "$mock_pid")"
    if [[ ! "$mock_cmd" =~ telegram_bot_new\.mock_messenger\.main.*--port\ $MOCK_PORT ]]; then
      echo "port $MOCK_PORT is in use by another process: $mock_cmd" >&2
      exit 1
    fi
    echo "$mock_pid" >"$PID_MOCK_FILE"
    echo "mock already listening on :$MOCK_PORT (pid=$mock_pid), reusing."
  else
    "$PYTHON_BIN" -m telegram_bot_new.mock_messenger.main \
      --host "$MOCK_HOST" \
      --port "$MOCK_PORT" \
      --db-path "$MOCK_DB_PATH" \
      --data-dir "$MOCK_DATA_DIR" \
      >"$MOCK_OUT_LOG" 2>"$MOCK_ERR_LOG" &
    mock_pid=$!
    echo "$mock_pid" >"$PID_MOCK_FILE"
    started_mock_by_up=1
    if ! wait_http_ok "http://$MOCK_HOST:$MOCK_PORT/healthz" 80; then
      echo "mock failed to start. see: $MOCK_ERR_LOG" >&2
      exit 1
    fi
    echo "mock started (pid=$mock_pid) at http://$MOCK_HOST:$MOCK_PORT"
  fi

  bot_pid="$(listener_pid "$BOT_PORT")"
  if [[ -n "$bot_pid" ]]; then
    local bot_cmd
    bot_cmd="$(pid_command "$bot_pid")"
    if [[ "$bot_cmd" =~ telegram_bot_new\.main\ run-bot.*--bot-id\ $BOT_ID.*--embedded-port\ $BOT_PORT ]]; then
      echo "stopping existing bot on :$BOT_PORT (pid=$bot_pid) before foreground run."
      stop_pid "$bot_pid" "bot"
      rm -f "$PID_BOT_FILE"
    else
      echo "port $BOT_PORT is in use by another process: $bot_cmd" >&2
      exit 1
    fi
  fi

  echo ""
  echo "UI:      http://$MOCK_HOST:$MOCK_PORT/_mock/ui?token=$VIRTUAL_TOKEN&chat_id=1001&user_id=9001"
  echo "Health:  http://$BOT_HOST:$BOT_PORT/healthz"
  echo "Mode:    foreground (Ctrl+C to stop)"
  echo ""

  cleanup_up() {
    rm -f "$PID_BOT_FILE"
    if [[ "$started_mock_by_up" -eq 1 ]]; then
      stop_pid "$mock_pid" "mock"
      rm -f "$PID_MOCK_FILE"
    fi
  }
  trap cleanup_up EXIT INT TERM

  TELEGRAM_API_BASE_URL="http://$MOCK_HOST:$MOCK_PORT" \
  TELEGRAM_VIRTUAL_TOKEN="$VIRTUAL_TOKEN" \
  PYTHONUNBUFFERED=1 \
  "$PYTHON_BIN" -m telegram_bot_new.main run-bot \
    --config "$CONFIG_PATH" \
    --bot-id "$BOT_ID" \
    --embedded-host "$BOT_HOST" \
    --embedded-port "$BOT_PORT"
  rc=$?
  exit "$rc"
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
