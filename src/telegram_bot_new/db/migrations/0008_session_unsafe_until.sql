-- Persist time-limited unsafe mode per session.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS unsafe_until BIGINT;
