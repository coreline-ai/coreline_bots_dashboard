# telegram_bot_new 개선 PR 체크리스트

## PR-1: 콜백 ACK 누락 방지 (최우선)
- 목표: `callback_query`는 어떤 입력이 와도 `answerCallbackQuery`를 반환하도록 보장.
- 변경:
- `src/telegram_bot_new/telegram/commands.py`에서 `parsed.callback_query_id`는 있지만 `callback_data`가 없을 때도 ACK.
- `_handle_callback` 내부 예외 발생 시 fallback ACK 추가.
- 수용조건:
- Telegram 클라이언트에서 버튼 스피너가 남지 않음.
- malformed callback payload 테스트 추가.
- 검증:
- `pytest -q tests/test_telegram_commands.py`

## PR-2: 세션 단일성 보장 (동시성)
- 목표: 같은 `(bot_id, chat_id)`에서 active session 중복 생성 방지.
- 변경:
- DB에 active session 유니크 제약(부분 인덱스) 추가.
- `get_or_create_active_session`을 원자적 upsert 패턴으로 보강.
- 수용조건:
- 동시 요청 부하에서도 active session 1개만 유지.
- 검증:
- race 테스트 추가.
- `pytest -q tests/test_repository_utils.py`

## PR-3: Supervisor 종료 안정성
- 목표: 부모 종료 시 자식 프로세스가 고아화되지 않도록 정리.
- 변경:
- `src/telegram_bot_new/supervisor.py`에 SIGINT/SIGTERM 처리.
- 자식 프로세스 terminate/kill 타임아웃 로직 추가.
- 수용조건:
- 종료 시 하위 `run-bot`/`run-gateway` 프로세스가 정상 종료.
- 검증:
- supervisor 통합 테스트 추가.

## PR-4: 아티팩트 스캔 비용 제한
- 목표: `_find_recent_files` 재귀 탐색으로 인한 I/O 비용/지연 축소.
- 변경:
- 스캔 루트 화이트리스트(`workspace`, `artifact_dir`) 기반 제한.
- 최대 파일 수/시간 예산 제한 옵션 추가.
- 수용조건:
- 대용량 디렉토리에서도 run 후 응답 지연 악화 없음.
- 검증:
- `tests/test_run_worker_artifacts.py` 확장.

## PR-5: 운영 보안 기본값 상향
- 목표: 기본 sandbox 정책을 안전한 값으로 전환.
- 변경:
- `settings.py` 기본 sandbox를 `workspace-write` 또는 `read-only`로 조정.
- README/샘플 config에 운영 권장값 명시.
- 수용조건:
- 기본 설치 직후 위험 권한으로 실행되지 않음.
- 검증:
- `pytest -q tests/test_settings.py`

## PR-6: Observability 확장
- 목표: 장애 지점 추적 가능한 메트릭/로그 보강.
- 변경:
- update/run job status별 카운터 메트릭 추가.
- webhook reject(401/400), callback ack, rate-limit 재시도 카운터 추가.
- 수용조건:
- 장애 시 어떤 단계에서 막혔는지 메트릭만으로 판단 가능.

## 실행 순서 권장
1. PR-1
2. PR-2
3. PR-3
4. PR-4
5. PR-5
6. PR-6

## 최종 검증 공통
- `PYTHONPATH=src ../.venv/bin/pytest -q`
- webhook/polling 각각 스모크:
- `/start`, 일반 텍스트 run, `/stop`, 버튼 콜백(summary/regen/next/stop), 문서/이미지 전송

## 고정 진행 순서 (운영 규칙)
아래 4단계를 반드시 순서대로 수행:
1. 수정
2. 자동 테스트
3. 실행 테스트
4. 실행 가능 완료 보고

### 원클릭 검증 명령
```bash
./scripts/verify-release-flow.sh
```
