-- Append-only audit logs for commands and run lifecycle.

CREATE TABLE IF NOT EXISTS audit_logs (
  id VARCHAR(64) PRIMARY KEY,
  bot_id VARCHAR(64) NOT NULL,
  chat_id VARCHAR(255),
  session_id VARCHAR(64),
  action VARCHAR(64) NOT NULL,
  result VARCHAR(32) NOT NULL,
  detail_json TEXT,
  created_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_bot_id ON audit_logs (bot_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_chat_id ON audit_logs (chat_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_session_id ON audit_logs (session_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_bot_chat_created ON audit_logs (bot_id, chat_id, created_at DESC);
