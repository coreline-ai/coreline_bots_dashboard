-- Initial schema for telegram_bot_new MVP

CREATE TABLE IF NOT EXISTS bots (
  bot_id VARCHAR(64) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  mode VARCHAR(32) NOT NULL,
  owner_user_id BIGINT NOT NULL,
  adapter_name VARCHAR(32) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_updates (
  bot_id VARCHAR(64) NOT NULL,
  update_id BIGINT NOT NULL,
  chat_id VARCHAR(255),
  payload_json TEXT NOT NULL,
  received_at BIGINT NOT NULL,
  PRIMARY KEY (bot_id, update_id)
);

CREATE TABLE IF NOT EXISTS telegram_update_jobs (
  id VARCHAR(64) PRIMARY KEY,
  bot_id VARCHAR(64) NOT NULL,
  update_id BIGINT NOT NULL,
  status VARCHAR(32) NOT NULL,
  lease_owner VARCHAR(255),
  lease_expires_at BIGINT,
  available_at BIGINT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE (bot_id, update_id)
);
CREATE INDEX IF NOT EXISTS ix_telegram_update_jobs_bot_status_available
  ON telegram_update_jobs (bot_id, status, available_at);

CREATE TABLE IF NOT EXISTS sessions (
  session_id VARCHAR(64) PRIMARY KEY,
  bot_id VARCHAR(64) NOT NULL,
  chat_id VARCHAR(255) NOT NULL,
  adapter_name VARCHAR(32) NOT NULL,
  adapter_thread_id VARCHAR(128),
  status VARCHAR(32) NOT NULL,
  rolling_summary_md TEXT NOT NULL DEFAULT '',
  last_turn_at BIGINT,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_bot_chat_updated
  ON sessions (bot_id, chat_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS turns (
  turn_id VARCHAR(64) PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  bot_id VARCHAR(64) NOT NULL,
  chat_id VARCHAR(255) NOT NULL,
  user_text TEXT NOT NULL,
  assistant_text TEXT,
  status VARCHAR(32) NOT NULL,
  error_text TEXT,
  started_at BIGINT,
  finished_at BIGINT,
  created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_turns_bot_chat_created
  ON turns (bot_id, chat_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cli_run_jobs (
  id VARCHAR(64) PRIMARY KEY,
  turn_id VARCHAR(64) NOT NULL UNIQUE REFERENCES turns(turn_id) ON DELETE CASCADE,
  bot_id VARCHAR(64) NOT NULL,
  chat_id VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL,
  lease_owner VARCHAR(255),
  lease_expires_at BIGINT,
  available_at BIGINT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cli_run_jobs_bot_status_available
  ON cli_run_jobs (bot_id, status, available_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cli_run_jobs_bot_chat_active
  ON cli_run_jobs (bot_id, chat_id)
  WHERE status IN ('queued', 'leased', 'in_flight');

CREATE TABLE IF NOT EXISTS cli_events (
  id BIGSERIAL PRIMARY KEY,
  turn_id VARCHAR(64) NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
  bot_id VARCHAR(64) NOT NULL,
  seq INTEGER NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  payload_json TEXT NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE (turn_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_cli_events_bot_turn
  ON cli_events (bot_id, turn_id, seq);

CREATE TABLE IF NOT EXISTS session_summaries (
  id VARCHAR(64) PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  bot_id VARCHAR(64) NOT NULL,
  turn_id VARCHAR(64) NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
  summary_md TEXT NOT NULL,
  created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_session_summaries_session_created
  ON session_summaries (session_id, created_at DESC);