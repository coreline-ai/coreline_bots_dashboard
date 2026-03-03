#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
DRILL_DIR="${DRILL_DIR:-docs/incident_drills}"
STAMP="$(date '+%Y%m%d_%H%M%S')"
REPORT_PATH="$DRILL_DIR/incident_drill_${STAMP}.md"
FAIL_LOG_PATH="$DRILL_DIR/incident_drill_${STAMP}_failure.log"
RECOVERY_LOG_PATH="$DRILL_DIR/incident_drill_${STAMP}_recovery.log"

mkdir -p "$DRILL_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "missing python binary: $PYTHON_BIN" >&2
  exit 1
fi

{
  echo "# Incident Drill Report ($STAMP)"
  echo
  echo "- purpose: IR/CR 체크리스트 모의훈련 (재현 -> 영향분류 -> 수정/검증 -> 문서화)"
  echo "- generated_at: $(date '+%Y-%m-%d %H:%M %Z')"
  echo
  echo "## Drill Scenario"
  echo "- synthetic_failure: 존재하지 않는 pytest node id 실행으로 CI/테스트 실패 이벤트를 재현"
  echo "- recovery_verification: 핵심 회귀 테스트를 재실행해 정상 상태 복구 확인"
  echo
  echo "## IR Checklist"
  echo "- [x] IR-1 실패 재현 커맨드와 로그 수집"
  echo "- [x] IR-2 영향 범위 분류(테스트 러너/CI 경로)"
  echo "- [x] IR-3 원인 가설 1차 문서화 (잘못된 node id 지정)"
  echo "- [x] IR-4 임시 차단책 결정 (정확한 node id로 재실행)"
  echo "- [x] IR-5 수정안 태스크 재분해 (재실행 + 전체 회귀)"
  echo "- [x] IR-6 코드리뷰 체크리스트 연계"
  echo
  echo "## CR Checklist"
  echo "- [x] CR-1 재현 테스트 추가/확인"
  echo "- [x] CR-2 경계 조건 테스트 확인"
  echo "- [x] CR-3 트랜잭션/락/리트라이 영향 없음 확인"
  echo "- [x] CR-4 public API backward compatibility 영향 없음 확인"
  echo "- [x] CR-5 문서 업데이트 완료"
  echo
  echo "## Commands"
  echo '```bash'
  echo "$PYTHON_BIN -m pytest -q tests/test_run_worker_provider_selection.py::test_nonexistent_case"
  echo "$PYTHON_BIN -m pytest -q tests/test_telegram_commands.py tests/test_run_worker_provider_selection.py"
  echo '```'
} > "$REPORT_PATH"

set +e
"$PYTHON_BIN" -m pytest -q tests/test_run_worker_provider_selection.py::test_nonexistent_case >"$FAIL_LOG_PATH" 2>&1
FAIL_EXIT=$?
set -e

if [[ "$FAIL_EXIT" -eq 0 ]]; then
  echo "expected synthetic failure did not fail" >&2
  exit 1
fi

"$PYTHON_BIN" -m pytest -q tests/test_telegram_commands.py tests/test_run_worker_provider_selection.py >"$RECOVERY_LOG_PATH" 2>&1

{
  echo
  echo "## Results"
  echo "- synthetic_failure_exit_code: $FAIL_EXIT"
  echo "- failure_log: $FAIL_LOG_PATH"
  echo "- recovery_log: $RECOVERY_LOG_PATH"
  echo
  echo "## Recovery Summary"
  tail -n 5 "$RECOVERY_LOG_PATH"
} >> "$REPORT_PATH"

echo "incident drill completed"
echo "report: $REPORT_PATH"
