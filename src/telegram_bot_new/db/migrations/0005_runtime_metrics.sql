-- Runtime metric counters used by app-level observability endpoints.

CREATE TABLE IF NOT EXISTS runtime_metric_counters (
  bot_id VARCHAR(64) NOT NULL,
  metric_key VARCHAR(128) NOT NULL,
  metric_value BIGINT NOT NULL DEFAULT 0,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (bot_id, metric_key)
);

CREATE INDEX IF NOT EXISTS ix_runtime_metric_counters_bot_key
  ON runtime_metric_counters (bot_id, metric_key);
