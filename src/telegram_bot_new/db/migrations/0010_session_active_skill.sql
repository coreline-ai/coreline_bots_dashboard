-- Persist selected skill profile per active session.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS active_skill VARCHAR(128);
