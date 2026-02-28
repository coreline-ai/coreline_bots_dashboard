-- Action tokens and deferred button actions for Codex-backed inline callbacks

CREATE TABLE IF NOT EXISTS action_tokens (
  token VARCHAR(64) PRIMARY KEY,
  bot_id VARCHAR(64) NOT NULL,
  chat_id VARCHAR(255) NOT NULL,
  action VARCHAR(32) NOT NULL,
  payload_json TEXT NOT NULL,
  expires_at BIGINT NOT NULL,
  consumed_at BIGINT,
  created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_action_tokens_bot_chat_expires
  ON action_tokens (bot_id, chat_id, expires_at);

CREATE TABLE IF NOT EXISTS deferred_button_actions (
  id VARCHAR(64) PRIMARY KEY,
  bot_id VARCHAR(64) NOT NULL,
  chat_id VARCHAR(255) NOT NULL,
  session_id VARCHAR(64) NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  action_type VARCHAR(32) NOT NULL,
  prompt_text TEXT NOT NULL,
  origin_turn_id VARCHAR(64) NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
  status VARCHAR(32) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_deferred_button_actions_bot_chat_status_created
  ON deferred_button_actions (bot_id, chat_id, status, created_at);
