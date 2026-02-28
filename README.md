# telegram_bot_new

Standalone MVP bridge between Telegram and CLI adapters (Codex/Gemini/Claude supported).

## Goals
- Receive Telegram webhook updates.
- Queue updates and CLI runs in PostgreSQL.
- Stream all adapter events to Telegram with ordered delivery and retry.
- Keep session continuity using `thread_id` resume.
- Persist rolling summaries every turn.
- Support multi-bot process isolation with supervisor.
- Support both runtime modes: `embedded` and `gateway`.

## Runtime Modes
- `embedded`: one process per bot, each process hosts webhook API and workers.
- `gateway`: one shared webhook API process + one worker-only process per bot.

## Directory Layout
- `src/telegram_bot_new/main.py`: CLI entrypoint.
- `src/telegram_bot_new/supervisor.py`: multi-process supervisor with restart backoff.
- `src/telegram_bot_new/runtime_embedded.py`: embedded bot runtime.
- `src/telegram_bot_new/runtime_gateway.py`: shared gateway runtime.
- `src/telegram_bot_new/adapters/`: adapter SDK + codex/gemini/claude/echo adapter.
- `src/telegram_bot_new/services/`: session, run, summary services.
- `src/telegram_bot_new/workers/`: update worker, run worker.
- `src/telegram_bot_new/db/`: models, repository, SQL migration.

## Requirements
- Python 3.11+
- PostgreSQL
- Telegram bot token(s)
- CLI binaries in PATH for providers you use (`codex`, `gemini`, `claude`)

## Local PostgreSQL (Docker Compose)
```bash
docker compose up -d postgres
```

## Setup
```bash
cd telegram_bot_new
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e .[dev]
copy .env.example .env
copy config/bots.example.yaml config/bots.yaml
```

Edit `.env` and `config/bots.yaml`.

Provider model example in `bots.yaml`:
```yaml
bots:
  - telegram_token: TELEGRAM_BOT_TOKEN
    adapter: codex
    codex:
      model: gpt-5
      sandbox: workspace-write
    gemini:
      model: gemini-2.5-pro
    claude:
      model: claude-sonnet-4-5
```

### Token-only quick start
If you only set `TELEGRAM_BOT_TOKEN` in `.env`, the app starts a single embedded bot in polling mode.
No webhook URL, path secret, or owner id is required for local MVP usage.
`config/bots.yaml` can stay as:
```yaml
bots:
  - telegram_token: TELEGRAM_BOT_TOKEN
```

If `TELEGRAM_BOT_TOKEN` is empty and `TELEGRAM_API_BASE_URL` points to local mock
(`http://127.0.0.1:...` or `http://localhost:...`), a virtual token is auto-used:
`TELEGRAM_VIRTUAL_TOKEN` (default: `mock_token_1`).

### PowerShell quick bootstrap (Windows)
```powershell
.\scripts\bootstrap-local.ps1
```

## Run
### Supervisor (recommended)
```bash
python -m telegram_bot_new.main supervisor
```

### Single bot process
```bash
python -m telegram_bot_new.main run-bot --bot-id bot-1
```

### Shared gateway only
```bash
python -m telegram_bot_new.main run-gateway --config config/bots.yaml --host 0.0.0.0 --port 4312
```

### PowerShell run helper
```powershell
.\scripts\run-local.ps1 -Mode supervisor
.\scripts\run-local.ps1 -Mode run-bot -BotId bot-1
.\scripts\run-local.ps1 -Mode run-gateway
```

## Local Mock Messenger
Use the built-in Telegram-compatible mock server to test without Telegram.

### One-command local fixed stack (macOS/Linux)
Recommended for stable local testing where one command starts both mock + bot.
```bash
./scripts/run-local.sh
```

Useful commands:
```bash
./scripts/run-local.sh status
./scripts/run-local.sh logs
./scripts/run-local.sh stop
```

Fixed endpoints:
- Mock UI: `http://127.0.0.1:9082/_mock/ui?token=mock_token_1&chat_id=1001&user_id=9001`
- Bot health: `http://127.0.0.1:8600/healthz`

### Multi-bot local stack (mock + supervisor)
Run true multi-bot test mode where multiple bot instances from `config/bots.multibot.yaml`
are started in parallel and tested from one mock UI.

```bash
./scripts/run-local-multibot.sh start
```

Custom config example:
```bash
CONFIG_PATH=config/bots.yaml ./scripts/run-local-multibot.sh start
```

Useful commands:
```bash
./scripts/run-local-multibot.sh status
./scripts/run-local-multibot.sh logs
./scripts/run-local-multibot.sh stop
./scripts/verify-multibot-smoke.sh
./scripts/verify-mock-ui-e2e.sh
```

Multi-bot UI:
- `http://127.0.0.1:9082/_mock/ui`
- Left sidebar supports profile add/select and parallel send.

### Start mock server only
```powershell
.\scripts\run-mock-messenger.ps1
```

Default UI:
- `http://127.0.0.1:9082/_mock/ui`
- First load auto-fills token with `mock_token_1` (or last used value in browser localStorage).

### Start mock + bot together
```powershell
.\scripts\run-local-with-mock.ps1 -Config config/bots.yaml
```

This command sets:
- `TELEGRAM_API_BASE_URL=http://127.0.0.1:9082`
- `TELEGRAM_VIRTUAL_TOKEN=mock_token_1` (if not set)

You can also set this in `.env` manually:
```env
TELEGRAM_API_BASE_URL=http://127.0.0.1:9082
```

### Mock API Coverage
- `POST /bot{token}/getUpdates`
- `POST /bot{token}/setWebhook`
- `POST /bot{token}/deleteWebhook`
- `POST /bot{token}/sendMessage`
- `POST /bot{token}/editMessageText`
- `POST /bot{token}/answerCallbackQuery`
- `POST /bot{token}/sendDocument`
- `POST /bot{token}/sendPhoto`

### Run mock + Codex bridge without real Telegram token
```powershell
.\scripts\run-mock-codex-bridge.ps1
```

Default virtual token:
- `mock_token_1`
- Direct UI URL with preset token is written to `%TEMP%\telegram_bot_new_runtime\pids.json` as `ui_url_with_token`.

Codex bridge now streams live progress to chat:
- `bridge_status` heartbeat (`running... elapsed=Ns`)
- normalized Codex events (`reasoning`, `command_started`, `command_completed`, `assistant_message`, `turn_completed`)
- timeout/error status (default timeout: `900s`)
- lightweight bridge commands in chat:
  - `/status`: show current `thread_id`
  - `/new`: reset thread and start fresh context
  - `/youtube <query>`: search YouTube and send a `watch?v=...` URL (Telegram native preview card)

Stop:
```powershell
.\scripts\stop-mock-codex-bridge.ps1
```

### Mock UI/Test API
- `GET /_mock/threads`
- `POST /_mock/send`
- `GET /_mock/messages`
- `GET /_mock/document/{document_id}?token=...`
- `GET /_mock/state`
- `GET /_mock/bot_catalog`
- `GET /_mock/bot_diagnostics?bot_id=<id>&token=<token>&chat_id=<chat>&limit=<n>`

UI behavior notes:
- Timeline auto-scroll only follows when you are already near the bottom.
- Text selection/copy is preserved (refresh does not force-jump while selecting).
- `sendDocument` image files (`png/jpg/jpeg/gif/webp/bmp/svg`) render inline in timeline.
- `sendDocument` HTML files (`.html/.htm`) render inline with iframe preview in timeline.
- Image intent prompts such as `꽃 이미지 만들고 현재 이미지 창에 보여줘` are handled by bridge hinting + recent-image fallback scan.
- HTML intent prompts such as `랜딩 페이지 html css로 만들어서 보여줘` are handled by bridge hinting + recent-html fallback scan.
- Bridge quick demo command in chat: `/demo-landing` (creates a sample HTML+CSS landing page and sends it).

## Telegram Commands (MVP)
- `/start`
- `/help`
- `/new`
- `/status`
- `/reset`
- `/summary`
- `/mode` and `/mode <codex|gemini|claude>`
- `/providers` (installed binaries + default models)
- `/stop`
- `/youtube <query>` (send top YouTube result with Telegram native preview)
- plain text: enqueue adapter run

Provider switching notes:
- `/mode <provider>` switches provider per chat session.
- Existing rolling summary is kept and auto-injected as recovery preamble.
- Provider thread id is reset on switch, so continuity comes from summary memory.

Natural language shortcut is also supported:
- `python asyncio tutorial 유튜브 찾아줘`
- `find youtube rust async channels`

## Event Streaming
- All adapter events are persisted to `cli_events`.
- Telegram line format: `[seq][time][type] content`.
- One live message is edited until `3800` chars, then continuation message is created.
- Telegram rate limit responses are retried in-order.
- On delivery failure, `delivery_error` event is persisted.
- Generated artifacts are forwarded to Telegram too:
  - image files are sent via `sendPhoto` (fallback `sendDocument`)
  - html files are sent via `sendDocument`

## Metrics
- Endpoint: `GET /metrics`
- Base counters:
  - `telegram_update_jobs`
  - `cli_run_jobs`
  - `in_flight_runs`
  - `telegram_updates_total`
- Status breakdown:
  - `telegram_update_jobs_by_status`
  - `cli_run_jobs_by_status`
- Runtime counters:
  - `webhook_accept_total`
  - `webhook_duplicate_update`
  - `webhook_reject_*`
  - `callback_ack_success`
  - `callback_ack_failed`
  - `telegram_rate_limit_retry_total`
  - `telegram_rate_limit_retry.<method>`

## Notes
- Access control is owner-only (`owner_user_id` in `bots.yaml`).
- If `owner_user_id` is unset, access is open to any Telegram user who can message the bot.
- Default Codex sandbox is `workspace-write`.
- Session summary is deterministic rule-based and updated every turn.

## Tests
```bash
pytest
```
