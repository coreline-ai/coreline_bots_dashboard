#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MOCK_BASE_URL="${MOCK_BASE_URL:-http://127.0.0.1:9082}"
RUNNER="${RUNNER:-./scripts/run-local-multibot.sh}"
# Use dedicated smoke chats by default to avoid mutating user's primary sessions.
CHAT_A="${CHAT_A:-91001}"
CHAT_B="${CHAT_B:-91002}"
USER_ID="${USER_ID:-9001}"

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
  local token="$1"
  local chat_id="$2"
  local text="$3"
  curl -fsS -X POST "$MOCK_BASE_URL/_mock/send" \
    -H 'content-type: application/json' \
    -d "{\"token\":\"$token\",\"chat_id\":$chat_id,\"user_id\":$USER_ID,\"text\":\"$text\"}" >/dev/null
}

messages_json() {
  local token="$1"
  local chat_id="$2"
  curl -fsS "$MOCK_BASE_URL/_mock/messages?token=$token&chat_id=$chat_id&limit=140"
}

max_message_id() {
  local token="$1"
  local chat_id="$2"
  messages_json "$token" "$chat_id" | jq -r '(.result.messages | map(.message_id) | max) // 0'
}

wait_for_text_since() {
  local token="$1"
  local chat_id="$2"
  local min_id="$3"
  local pattern="$4"
  local timeout_sec="${5:-30}"
  local elapsed=0
  while [[ "$elapsed" -lt "$timeout_sec" ]]; do
    if messages_json "$token" "$chat_id" | jq -e --arg p "$pattern" --argjson min_id "$min_id" \
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

extract_adapter_since() {
  local token="$1"
  local chat_id="$2"
  local min_id="$3"
  messages_json "$token" "$chat_id" | jq -r --argjson min_id "$min_id" '
    .result.messages
    | map(select((.message_id // 0) > $min_id) | (.text // ""))
    | map(try capture("adapter=(?<a>codex|gemini|claude)").a catch null)
    | map(select(. != null))
    | .[-1] // "unknown"
  '
}

choose_next_provider() {
  local current="$1"
  case "$current" in
    codex) echo "gemini" ;;
    gemini) echo "claude" ;;
    claude) echo "codex" ;;
    *) echo "codex" ;;
  esac
}

require_bin curl
require_bin jq

step "1/4" "수정 단계 확인"
echo "멀티봇 스모크를 실행합니다."

step "2/4" "자동 테스트"
echo "pytest는 별도 파이프라인에서 실행되며, 본 스크립트는 실행 스모크에 집중합니다."

step "3/4" "실행 테스트"
if ! health_ok "$MOCK_BASE_URL"; then
  echo "mock server down. trying detached start..."
  "$RUNNER" start || true
fi
if ! health_ok "$MOCK_BASE_URL"; then
  echo "mock server is unavailable: $MOCK_BASE_URL" >&2
  exit 1
fi

catalog_json="$(curl -fsS "$MOCK_BASE_URL/_mock/bot_catalog")"
embedded_rows_raw="$(echo "$catalog_json" | jq -r '.result.bots[] | select(.mode=="embedded") | [.bot_id,.token] | @tsv')"
embedded_count="$(echo "$embedded_rows_raw" | sed '/^\s*$/d' | wc -l | tr -d ' ')"
if [[ "$embedded_count" -lt 2 ]]; then
  echo "need at least 2 embedded bots in config/bots.multibot.yaml (or override CONFIG_PATH) for multibot smoke" >&2
  exit 1
fi

BOT_A="$(echo "$embedded_rows_raw" | sed -n '1p' | awk '{print $1}')"
TOKEN_A="$(echo "$embedded_rows_raw" | sed -n '1p' | awk '{print $2}')"
BOT_B="$(echo "$embedded_rows_raw" | sed -n '2p' | awk '{print $1}')"
TOKEN_B="$(echo "$embedded_rows_raw" | sed -n '2p' | awk '{print $2}')"

echo "target bots: $BOT_A, $BOT_B"

base_a="$(max_message_id "$TOKEN_A" "$CHAT_A")"
base_b="$(max_message_id "$TOKEN_B" "$CHAT_B")"

send_message "$TOKEN_A" "$CHAT_A" "/start"
send_message "$TOKEN_A" "$CHAT_A" "하이 너는 누구니"

send_message "$TOKEN_B" "$CHAT_B" "/start"
send_message "$TOKEN_B" "$CHAT_B" "하이 너는 누구니"

wait_for_text_since "$TOKEN_A" "$CHAT_A" "$base_a" "turn_completed" 35 || {
  echo "smoke failed: turn completion missing for $BOT_A" >&2
  exit 1
}
wait_for_text_since "$TOKEN_B" "$CHAT_B" "$base_b" "turn_completed" 35 || {
  echo "smoke failed: turn completion missing for $BOT_B" >&2
  exit 1
}

status_bootstrap_a="$(max_message_id "$TOKEN_A" "$CHAT_A")"
status_bootstrap_b="$(max_message_id "$TOKEN_B" "$CHAT_B")"
send_message "$TOKEN_A" "$CHAT_A" "/status"
send_message "$TOKEN_B" "$CHAT_B" "/status"

wait_for_text_since "$TOKEN_A" "$CHAT_A" "$status_bootstrap_a" "bot=$BOT_A" 30 || {
  echo "smoke failed: /status not reflected for $BOT_A" >&2
  exit 1
}
wait_for_text_since "$TOKEN_B" "$CHAT_B" "$status_bootstrap_b" "bot=$BOT_B" 30 || {
  echo "smoke failed: /status not reflected for $BOT_B" >&2
  exit 1
}

current_adapter_a="$(extract_adapter_since "$TOKEN_A" "$CHAT_A" "$status_bootstrap_a")"
current_adapter_b="$(extract_adapter_since "$TOKEN_B" "$CHAT_B" "$status_bootstrap_b")"
target_adapter_a="$(choose_next_provider "$current_adapter_a")"
target_adapter_b="$(choose_next_provider "$current_adapter_b")"

switch_base_a="$(max_message_id "$TOKEN_A" "$CHAT_A")"
switch_base_b="$(max_message_id "$TOKEN_B" "$CHAT_B")"

send_message "$TOKEN_A" "$CHAT_A" "/mode $target_adapter_a"
send_message "$TOKEN_B" "$CHAT_B" "/mode $target_adapter_b"

wait_for_text_since "$TOKEN_A" "$CHAT_A" "$switch_base_a" "mode switched: .*-> $target_adapter_a|mode unchanged: adapter=$target_adapter_a" 20 || {
  echo "smoke failed: provider switch $target_adapter_a missing for $BOT_A" >&2
  exit 1
}
wait_for_text_since "$TOKEN_B" "$CHAT_B" "$switch_base_b" "mode switched: .*-> $target_adapter_b|mode unchanged: adapter=$target_adapter_b" 20 || {
  echo "smoke failed: provider switch $target_adapter_b missing for $BOT_B" >&2
  exit 1
}

status_base_a="$(max_message_id "$TOKEN_A" "$CHAT_A")"
status_base_b="$(max_message_id "$TOKEN_B" "$CHAT_B")"
send_message "$TOKEN_A" "$CHAT_A" "/status"
send_message "$TOKEN_B" "$CHAT_B" "/status"

wait_for_text_since "$TOKEN_A" "$CHAT_A" "$status_base_a" "adapter=$target_adapter_a" 20 || {
  echo "smoke failed: adapter status $target_adapter_a missing for $BOT_A" >&2
  exit 1
}
wait_for_text_since "$TOKEN_B" "$CHAT_B" "$status_base_b" "adapter=$target_adapter_b" 20 || {
  echo "smoke failed: adapter status $target_adapter_b missing for $BOT_B" >&2
  exit 1
}

# restore providers to original adapter to keep smoke idempotent
restore_base_a="$(max_message_id "$TOKEN_A" "$CHAT_A")"
restore_base_b="$(max_message_id "$TOKEN_B" "$CHAT_B")"
send_message "$TOKEN_A" "$CHAT_A" "/mode $current_adapter_a"
send_message "$TOKEN_B" "$CHAT_B" "/mode $current_adapter_b"

wait_for_text_since "$TOKEN_A" "$CHAT_A" "$restore_base_a" "mode switched: .*-> $current_adapter_a|mode unchanged: adapter=$current_adapter_a" 20 || {
  echo "smoke failed: provider restore $current_adapter_a missing for $BOT_A" >&2
  exit 1
}
wait_for_text_since "$TOKEN_B" "$CHAT_B" "$restore_base_b" "mode switched: .*-> $current_adapter_b|mode unchanged: adapter=$current_adapter_b" 20 || {
  echo "smoke failed: provider restore $current_adapter_b missing for $BOT_B" >&2
  exit 1
}

step "4/4" "실행 가능 완료 보고"
echo "RESULT=PASS"
echo "BOTS=$BOT_A,$BOT_B"
echo "UI=$MOCK_BASE_URL/_mock/ui"
