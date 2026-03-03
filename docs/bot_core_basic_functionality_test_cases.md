# Bot Core Basic Functionality Test Cases

## Scope
- Provider/Model selection (including missing CLI behavior)
- Default provider fallback (`codex`)
- Role selection
- Project selection
- Multi-skill selection (`/skill a,b`)
- Minimum 3-bot self-test flow

## Expected Behavior
1. When no explicit adapter is available, the system defaults to `codex`.
2. Provider change and model change are independently selectable and validated per provider.
3. If a provider CLI is missing, run fails with a clear actionable message instead of crashing.
4. Role can be changed per bot via catalog API.
5. Project path can be selected and persisted per session.
6. Skills can be selected as multiple entries and persisted as a normalized list.

## Test Case Matrix
- [x] `TC-CORE-001` Default provider fallback is `codex`.
  - Automation: `tests/test_mock_messenger_api.py::test_mock_bot_catalog_add_endpoint_creates_missing_config`
  - Automation: `tests/test_mock_messenger_api.py::test_mock_routing_suggest_defaults_to_codex_without_bot_id`
- [x] `TC-CORE-002` Provider-specific model selection works and rejects invalid model.
  - Automation: `tests/test_telegram_commands.py::test_model_updates_session_model`
  - Automation: `tests/test_telegram_commands.py::test_model_rejects_unsupported_model`
- [x] `TC-CORE-003` Missing provider CLI is handled with recovery-oriented error message.
  - Automation: `tests/test_run_worker_provider_selection.py::test_process_run_job_reports_missing_provider_binary_with_standard_message`
- [x] `TC-CORE-004` Role selection is supported for each bot.
  - Automation: `tests/test_mock_messenger_api.py::test_mock_bot_catalog_role_update_for_three_bots`
- [x] `TC-CORE-005` Project selection is supported and persisted.
  - Automation: `tests/test_telegram_commands.py::test_project_updates_session_workdir`
- [x] `TC-CORE-006` Skill multi-selection is supported and prompt guidance is injected.
  - Automation: `tests/test_telegram_commands.py::test_skill_command_supports_multiple_skills`
  - Automation: `tests/test_skill_library.py::test_build_skill_instruction_supports_multiple_skills`
  - Automation: `tests/test_run_worker_provider_selection.py::test_process_run_job_injects_multiple_skills_guidance`
- [x] `TC-CORE-007` Core configuration flow succeeds for at least 3 bots.
  - Automation: `tests/test_telegram_commands.py::test_core_configuration_flow_runs_for_three_bots`

## Self-Test Execution
- [x] Command executed
```bash
PYTHONPATH=src python3.11 -m pytest -q \
  tests/test_skill_library.py \
  tests/test_telegram_commands.py \
  tests/test_run_worker_provider_selection.py \
  tests/test_mock_messenger_multibot_ui_model.py \
  tests/test_mock_messenger_api.py
```
- [x] Result: `89 passed, 46 warnings`
- [x] Minimum 3-bot test included and passed (`TC-CORE-007`)

## Notes
- Warnings are FastAPI `on_event` deprecation warnings and are non-blocking for current functionality.
- Multi-skill value is normalized as comma-separated unique skill IDs (order-preserving).
