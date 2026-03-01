# P0~P5 Execution Tickets (Immediate Runbook)

아래 티켓은 현재 코드베이스(`codex_chatbot_mvp`)에서 즉시 실행 가능한 단위로 분해했습니다.  
각 티켓은 완료 시점마다 자체 테스트를 실행하도록 설계했습니다.

## P0. Runtime Baseline Guardrail
- 목적: 봇 컷오프/런타임 프로파일 불일치를 즉시 식별
- 변경 파일:
  - `scripts/run-local-multibot.sh`
  - `src/telegram_bot_new/mock_messenger/api.py`
  - `src/telegram_bot_new/mock_messenger/web/index.html`
  - `src/telegram_bot_new/mock_messenger/web/app.js`
  - `src/telegram_bot_new/mock_messenger/web/styles.css`
- 작업 항목:
  - `MAX_BOTS` 기본값을 bot-7 포함 가능한 값으로 유지
  - `GET /_mock/runtime_profile` 제공 (effective/source/max/capped)
  - UI 사이드바에 runtime profile 메타 표시
- 테스트:
  - `pytest -q tests/test_mock_messenger_api.py -k runtime_profile`
  - `curl -s http://127.0.0.1:9082/_mock/runtime_profile | jq .`
- 수용 기준:
  - runtime profile 응답이 `effective_bots`, `source_bots`, `is_capped`를 포함
  - UI에서 runtime 메타가 표시되고 오류 시 에러 문구 표시

## P1. Control Tower MVP
- 목적: 봇 상태 집계/복구를 대시보드에서 단일 화면으로 제공
- 변경 파일:
  - `src/telegram_bot_new/mock_messenger/api.py`
  - `src/telegram_bot_new/mock_messenger/schemas.py`
  - `src/telegram_bot_new/mock_messenger/web/index.html`
  - `src/telegram_bot_new/mock_messenger/web/app.js`
  - `src/telegram_bot_new/mock_messenger/web/styles.css`
- 작업 항목:
  - `GET /_mock/control_tower`
  - `POST /_mock/control_tower/recover` (`stop_run`, `restart_session`)
  - Control Tower 패널 렌더 + 복구 버튼
- 테스트:
  - `pytest -q tests/test_mock_messenger_api.py -k "control_tower"`
  - `curl -s http://127.0.0.1:9082/_mock/control_tower | jq .result.summary`
- 수용 기준:
  - 각 bot row에 `state`, `reason`, `recommended_action` 존재
  - 복구 호출 시 `/stop` 또는 `/stop + /new`가 enqueue 되고 결과 반환

## P2. Routing Suggest + Skill Inventory API
- 목적: 자동 라우팅 추천과 설치된 스킬 관찰성 제공
- 변경 파일:
  - `src/telegram_bot_new/mock_messenger/api.py`
  - `src/telegram_bot_new/routing_policy.py`
  - `src/telegram_bot_new/skill_library.py`
  - `tests/test_mock_messenger_api.py`
  - `tests/test_routing_policy.py`
  - `tests/test_skill_library.py`
- 작업 항목:
  - `GET /_mock/routing/suggest?text=...&bot_id=...`
  - `GET /_mock/skills`
- 테스트:
  - `pytest -q tests/test_routing_policy.py tests/test_skill_library.py`
  - `pytest -q tests/test_mock_messenger_api.py -k "routing_suggest or mock_skills"`
- 수용 기준:
  - `@auto` 프롬프트에서 provider/model 추천값 반환
  - 로컬 skills 디렉토리의 `SKILL.md`를 API에서 나열

## P3. Debate Final Decision Summary
- 목적: 마지막 라운드에서 토론 결론 구조화 및 파싱 안정화
- 변경 파일:
  - `src/telegram_bot_new/mock_messenger/debate.py`
  - `src/telegram_bot_new/mock_messenger/schemas.py`
  - `tests/test_mock_debate_orchestrator.py`
- 작업 항목:
  - 마지막 턴 포맷 강화: `요약/결론/액션/신뢰도`
  - `decision_summary` 응답 포함
  - 라인 기반 라벨 파서 + fallback
- 테스트:
  - `pytest -q tests/test_mock_debate_orchestrator.py`
- 수용 기준:
  - debate status 응답에 `decision_summary` 포함
  - 라벨 일부 누락 시에도 summary/conclusion/action이 null-safe 또는 fallback으로 채워짐

## P4. Forensics Bundle + SLO Snapshot
- 목적: 장애 분석에 필요한 상태를 단일 API로 수집
- 변경 파일:
  - `src/telegram_bot_new/mock_messenger/api.py`
  - `tests/test_mock_messenger_api.py`
- 작업 항목:
  - `GET /_mock/forensics/bundle` 추가
  - 최근 turn 성공률/실패율/복구횟수 SLO 스냅샷 계산
  - Control Tower 상태 계산에 SLO 반영
- 테스트:
  - `pytest -q tests/test_mock_messenger_api.py -k "forensics_bundle or control_tower or runtime_profile"`
  - `curl -s "http://127.0.0.1:9082/_mock/forensics/bundle?bot_id=bot-a&token=mock_token_a&chat_id=1001" | jq .result.state`
- 수용 기준:
  - forensics 응답에 `runtime_profile`, `state`, `slo`, `diagnostics`, `audit_logs`, `messages`, `updates` 포함
  - turn success rate 임계치에 따라 `healthy/degraded/failing` 분기

## P5. End-to-End Smoke and Regression Gate
- 목적: UI/API/핵심 회귀를 한 번에 검증 후 배포 가능 상태 확보
- 변경 파일:
  - 테스트 코드 전체(수정 없음 가능)
  - 운영 스크립트/README(필요 시)
- 작업 항목:
  - 로컬 서버 기동, 핵심 엔드포인트 200 확인
  - 회귀 테스트 묶음 실행
- 테스트:
  - `pytest -q tests/test_mock_messenger_api.py tests/test_mock_debate_orchestrator.py tests/test_routing_policy.py tests/test_run_worker_provider_selection.py tests/test_mock_messenger_multibot_ui_model.py tests/test_telegram_commands.py tests/test_skill_library.py`
  - `curl -I http://127.0.0.1:9082/_mock/ui`
  - `curl -s http://127.0.0.1:9082/_mock/control_tower | jq .ok`
- 수용 기준:
  - 지정 회귀 테스트 전부 통과
  - `_mock/ui`, `_mock/control_tower`, `_mock/routing/suggest`, `_mock/runtime_profile` 모두 정상 응답

---

## 실행 순서
1. P0 적용/검증
2. P1 적용/검증
3. P2 적용/검증
4. P3 적용/검증
5. P4 적용/검증
6. P5 통합 회귀/스모크

## 롤백 원칙
- 각 티켓 단위로 커밋 분리
- 실패 시 해당 티켓 커밋만 revert (연쇄 티켓은 유지)
- 운영 중 장애 시 Control Tower Recover로 `stop_run -> restart_session` 순서 대응
