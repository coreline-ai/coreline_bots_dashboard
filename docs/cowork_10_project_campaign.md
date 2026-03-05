# Cowork 10-Project Execution Campaign

## Workflow Spec
- 역할 기반 상세 규격: `docs/role_based_workflow_spec_v1.md`

## Rule
- 각 프로젝트는 단일 작업으로 순차 실행한다.
- 완료 기준은 해당 프로젝트 테스트 통과다.
- 실패 시 즉시 코드 보강 후 동일 프로젝트를 재검증한다.

## Projects

### P1. Bot Registry 순차 ID/라벨 보장 + 삭제 슬롯 재사용
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_mock_messenger_api.py::test_mock_bot_catalog_add_reuses_deleted_alpha_slot`
  - `python3.11 -m pytest -q tests/test_mock_messenger_api.py::test_mock_bot_catalog_add_endpoint`

### P2. Gemini human-input 자동 provider fallback(codex/gpt-5)
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_mock_cowork_orchestrator.py::test_cowork_orchestrator_auto_fallbacks_gemini_human_input_to_codex`
  - `python3.11 -m pytest -q tests/test_run_worker_provider_selection.py::test_process_run_job_applies_gemini_human_input_provider_fallback`

### P3. Leader/Sub-agent 프롬프트 계약 강화(4단계)
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_cowork_project_contract_hardening.py::test_cowork_stage_prompts_include_contract_sections`

### P4. Run worker 동시성 풀
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_worker_heartbeat_metrics.py::test_run_worker_uses_configured_concurrency_pool`

### P5. ERR_CONNECTION_REFUSED 품질게이트 차단
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_cowork_project_contract_hardening.py::test_quality_gate_fails_on_connection_refused_trace`

### P6. Healthy/Degraded/Failing 상태 신뢰성(heartbeat 포함)
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_mock_messenger_api.py::test_mock_bot_diagnostics_endpoint_with_bot_down`

### P7. catalog/session 정합성과 unknown bot_id 힌트
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_mock_messenger_api.py::test_bot_diagnostics_unknown_bot_includes_cap_hint_when_capped`

### P8. Render 요청 완료 기준(실행 링크 필수)
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_mock_cowork_orchestrator.py::test_cowork_orchestrator_render_task_reworks_until_link_present`
  - `python3.11 -m pytest -q tests/test_mock_cowork_orchestrator.py::test_cowork_orchestrator_render_task_fails_when_link_missing`

### P9. 최종 결론 미완료 판정 차단
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_mock_cowork_orchestrator.py::test_cowork_orchestrator_fails_when_final_verdict_is_incomplete`

### P10. 품질게이트 재작업 루프 + 결과 링크 추출 보강
- [x] 상태
- 테스트:
  - `python3.11 -m pytest -q tests/test_cowork_project_contract_hardening.py::test_quality_gate_can_recover_execution_link_from_task_evidence`

## Execution Log
- [x] P1 완료
- [x] P2 완료
- [x] P3 완료
- [x] P4 완료
- [x] P5 완료
- [x] P6 완료
- [x] P7 완료
- [x] P8 완료
- [x] P9 완료
- [x] P10 완료
