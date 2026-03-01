-- Persist selected model per active session.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS adapter_model VARCHAR(128);
