#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TOKEN="${TOKEN:-mock_token_1}"
CHAT_ID="${CHAT_ID:-1001}"
USER_ID="${USER_ID:-9001}"
MOCK_BASE_URL="${MOCK_BASE_URL:-http://127.0.0.1:9082}"
BOT_BASE_URL="${BOT_BASE_URL:-http://127.0.0.1:8600}"
EXPECTED_BOT_ID="${EXPECTED_BOT_ID:-}"

AUTO_TEST_CMD="${AUTO_TEST_CMD:-./.venv/bin/python -m pytest -q tests/test_telegram_poller.py tests/test_telegram_commands.py tests/test_run_worker_provider_selection.py tests/test_gemini_adapter.py tests/test_claude_adapter.py tests/test_settings.py}"

step() {
  printf "\n[%s] %s\n" "$1" "$2"
}

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required binary: $1" >&2
    exit 1
  fi
}

health_ok() {
  curl -fsS "$1/healthz" >/dev/null 2>&1
}

send_message() {
  local text="$1"
  curl -fsS -X POST "$MOCK_BASE_URL/_mock/send" \
    -H 'content-type: application/json' \
    -d "{\"token\":\"$TOKEN\",\"chat_id\":$CHAT_ID,\"user_id\":$USER_ID,\"text\":\"$text\"}" >/dev/null
}

messages_json() {
  curl -fsS "$MOCK_BASE_URL/_mock/messages?token=$TOKEN&chat_id=$CHAT_ID&limit=80"
}

max_message_id() {
  messages_json | jq -r '(.result.messages | map(.message_id) | max) // 0'
}

wait_for_text_since() {
  local pattern="$1"
  local min_id="$2"
  local timeout_sec="${3:-20}"
  local elapsed=0
  while [[ "$elapsed" -lt "$timeout_sec" ]]; do
    if messages_json | jq -e --arg p "$pattern" --argjson min_id "$min_id" \
      '.result.messages
      | map(select((.message_id // 0) > $min_id) | (.text // ""))
      | join("\n")
      | test($p; "i")' >/dev/null; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

resolve_bot_id_by_token() {
  curl -fsS "$MOCK_BASE_URL/_mock/bot_catalog" | jq -r --arg token "$TOKEN" \
    '.result.bots[] | select(.token == $token) | .bot_id' | head -n1
}

require_bin curl
require_bin jq

step "1/4" "수정 단계 확인"
echo "코드 수정 반영 후 검증을 시작합니다. (수정 단계는 작업자가 선행)"

step "2/4" "자동 테스트"
echo "running: $AUTO_TEST_CMD"
eval "$AUTO_TEST_CMD"

step "3/4" "실행 테스트"
if ! health_ok "$MOCK_BASE_URL" || ! health_ok "$BOT_BASE_URL"; then
  echo "local stack is down. trying detached start..."
  ./scripts/run-local.sh start || true
fi

if ! health_ok "$MOCK_BASE_URL" || ! health_ok "$BOT_BASE_URL"; then
  echo "stack is still down after start. run './scripts/run-local.sh up' in another terminal, then retry." >&2
  exit 1
fi

if [[ -z "$EXPECTED_BOT_ID" ]]; then
  EXPECTED_BOT_ID="$(resolve_bot_id_by_token || true)"
fi
if [[ -z "$EXPECTED_BOT_ID" ]]; then
  echo "smoke failed: could not resolve bot_id for token=$TOKEN from /_mock/bot_catalog" >&2
  exit 1
fi

baseline_id="$(max_message_id)"
send_message "/start"
send_message "/status"
send_message "하이 너는 누구니"

if ! wait_for_text_since "ready" "$baseline_id" 20; then
  echo "smoke failed: /start response not found" >&2
  exit 1
fi
if ! wait_for_text_since "bot=$EXPECTED_BOT_ID" "$baseline_id" 20; then
  echo "smoke failed: /status response not found" >&2
  exit 1
fi
if ! wait_for_text_since "turn_completed" "$baseline_id" 30; then
  echo "smoke failed: run completion event not found" >&2
  exit 1
fi

step "4/4" "실행 가능 완료 보고"
echo "RESULT=PASS"
echo "UI=$MOCK_BASE_URL/_mock/ui?token=$TOKEN&chat_id=$CHAT_ID&user_id=$USER_ID"
echo "MOCK_HEALTH=$(curl -fsS "$MOCK_BASE_URL/healthz")"
echo "BOT_HEALTH=$(curl -fsS "$BOT_BASE_URL/healthz")"
echo "LAST_MESSAGES="
messages_json | jq -r --argjson min_id "$baseline_id" '.result.messages
  | map(select((.message_id // 0) > $min_id))
  | .[-10:]
  | .[]
  | "[\(.message_id)] \(.direction): \((.text // "") | gsub("\n"; " "))"'
