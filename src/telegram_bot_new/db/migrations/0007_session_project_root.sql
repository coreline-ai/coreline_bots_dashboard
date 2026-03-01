-- Persist per-session working directory for CLI execution.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS project_root VARCHAR(1024);
