# RCA: `unknown bot_id` under Multi-bot Parallel Runtime

## Symptom
- UI / diagnostics request for `bot-9` fails with:
  - `404: unknown bot_id: bot-9`
- `/ _mock/bot_catalog` only returns up to `bot-8` (or another truncated set).

## Why this happened (root cause)
1. The local runtime does **not** always run directly from `config/bots.multibot.yaml`.
2. `scripts/run-local-multibot.sh` generates an intermediate runtime config:
   - `.runlogs/local-multibot/bots.effective.yaml`
3. When `MAX_BOTS > 0`, this effective config is sliced to the first N bots.
4. Mock API and embedded workers use `bots.effective.yaml` as runtime truth, so:
   - bots outside the slice are not part of catalog
   - API returns `unknown bot_id` for them

In short: parallel workers can run, but only for bots included in **effective runtime config**.

## Architectural issue that amplified confusion
- `unknown bot_id` message did not explain cap/cutoff context.
- Operator had to manually infer whether the bot was typo/deleted/capped.
- Default cap (`MAX_BOTS=9`) made truncation implicit.

## Refactor applied
1. Runtime profile extraction centralized
   - `src/telegram_bot_new/mock_messenger/runtime_profile.py`
   - Single source for: `effective_bots`, `source_bots`, `is_capped`, source path resolution.
2. Context-rich unknown-bot explanation
   - If bot exists in source config but excluded by cap, error now explains:
     - capped state (`effective/source`)
     - required `MAX_BOTS>=k`
     - fix command hint (`MAX_BOTS=0` or higher N)
3. Routes unified to use same explanation logic
   - diagnostics routes
   - orchestration routes
   - bot catalog role/delete routes
4. Hidden cap removed as default behavior
   - `MAX_BOTS` default changed to `0` (= run all configured bots).
5. Runtime script resilience improved
   - python executable fallback chain (`.venv` -> `.pyshim` -> `python3.11` -> `python3`).

## Operational behavior after fix
- Default startup runs all configured bots unless operator sets `MAX_BOTS` intentionally.
- If capped intentionally and querying excluded bot:
  - API explicitly reports cap cause and required threshold.

## Validation
- Added regression test:
  - `tests/test_mock_messenger_api.py::test_bot_diagnostics_unknown_bot_includes_cap_hint_when_capped`
- Full relevant suites passed:
  - `97 passed` (mock API/cowork/debate + core command/worker suites)

## Recommended run command
```bash
cd /Users/hwan/projects/coreline_bots_dashboard
MAX_BOTS=0 ./scripts/run-local-multibot.sh up
```
