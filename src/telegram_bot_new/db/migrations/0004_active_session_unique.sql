-- Ensure one active session per (bot_id, chat_id).
-- Keep the latest active row and reset older duplicates first.

WITH ranked_active AS (
  SELECT
    session_id,
    ROW_NUMBER() OVER (
      PARTITION BY bot_id, chat_id
      ORDER BY updated_at DESC, created_at DESC, session_id DESC
    ) AS rn
  FROM sessions
  WHERE status = 'active'
)
UPDATE sessions
SET status = 'reset',
    adapter_thread_id = NULL
WHERE session_id IN (
  SELECT session_id
  FROM ranked_active
  WHERE rn > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_bot_chat_active
  ON sessions (bot_id, chat_id)
  WHERE status = 'active';
