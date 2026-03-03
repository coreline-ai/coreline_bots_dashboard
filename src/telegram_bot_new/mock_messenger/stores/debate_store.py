from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from telegram_bot_new.mock_messenger.store import MockMessengerStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def create_debate(
    self: MockMessengerStore,
    *,
    topic: str,
    rounds_total: int,
    max_turn_sec: int,
    fresh_session: bool,
    participants: list[dict[str, Any]],
    scope_key: str | None = None,
) -> str:
    debate_id = uuid.uuid4().hex
    now_ms = _now_ms()
    with self._lock:
        self._conn.execute(
            """
            INSERT INTO debates(
              debate_id, scope_key, topic, status, rounds_total, max_turn_sec, fresh_session,
              stop_requested, created_at, started_at, finished_at, error_summary
            )
            VALUES (?, ?, ?, 'queued', ?, ?, ?, 0, ?, NULL, NULL, NULL)
            """,
            (debate_id, scope_key, topic, rounds_total, max_turn_sec, 1 if fresh_session else 0, now_ms),
        )
        for index, participant in enumerate(participants, start=1):
            self._conn.execute(
                """
                INSERT INTO debate_participants(
                  debate_id, position, profile_id, label, bot_id, token, chat_id, user_id, adapter, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    debate_id,
                    index,
                    str(participant.get("profile_id") or ""),
                    str(participant.get("label") or ""),
                    str(participant.get("bot_id") or ""),
                    str(participant.get("token") or ""),
                    str(participant.get("chat_id") or ""),
                    str(participant.get("user_id") or ""),
                    str(participant.get("adapter") or "") or None,
                    now_ms,
                ),
            )
        self._conn.commit()
    return debate_id


def set_debate_running(self: MockMessengerStore, *, debate_id: str) -> None:
    now_ms = _now_ms()
    with self._lock:
        self._conn.execute(
            """
            UPDATE debates
            SET status = 'running',
                started_at = COALESCE(started_at, ?)
            WHERE debate_id = ?
            """,
            (now_ms, debate_id),
        )
        self._conn.commit()


def set_debate_stop_requested(self: MockMessengerStore, *, debate_id: str) -> None:
    with self._lock:
        self._conn.execute(
            "UPDATE debates SET stop_requested = 1 WHERE debate_id = ?",
            (debate_id,),
        )
        self._conn.commit()


def get_debate(self: MockMessengerStore, *, debate_id: str) -> dict[str, Any] | None:
    with self._lock:
        row = self._conn.execute(
            """
            SELECT debate_id, scope_key, topic, status, rounds_total, max_turn_sec, fresh_session, stop_requested,
                   created_at, started_at, finished_at, error_summary
            FROM debates
            WHERE debate_id = ?
            """,
            (debate_id,),
        ).fetchone()
    if row is None:
        return None
    return self._row_to_debate(row)


def get_active_debate(self: MockMessengerStore, *, scope_key: str | None = None) -> dict[str, Any] | None:
    with self._lock:
        if scope_key is None:
            row = self._conn.execute(
                """
                SELECT debate_id, scope_key, topic, status, rounds_total, max_turn_sec, fresh_session, stop_requested,
                       created_at, started_at, finished_at, error_summary
                FROM debates
                WHERE status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT debate_id, scope_key, topic, status, rounds_total, max_turn_sec, fresh_session, stop_requested,
                       created_at, started_at, finished_at, error_summary
                FROM debates
                WHERE status IN ('queued', 'running')
                  AND COALESCE(scope_key, '') = COALESCE(?, '')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (scope_key,),
            ).fetchone()
    if row is None:
        return None
    return self._row_to_debate(row)


def insert_debate_turn_start(
    self: MockMessengerStore,
    *,
    debate_id: str,
    round_no: int,
    speaker_position: int,
    speaker_bot_id: str,
    speaker_label: str,
    prompt_text: str,
) -> int:
    started_at = _now_ms()
    with self._lock:
        cursor = self._conn.execute(
            """
            INSERT INTO debate_turns(
              debate_id, round_no, speaker_position, speaker_bot_id, speaker_label,
              prompt_text, response_text, status, error_text, started_at, finished_at, duration_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, 'running', NULL, ?, NULL, NULL)
            """,
            (debate_id, round_no, speaker_position, speaker_bot_id, speaker_label, prompt_text, started_at),
        )
        self._conn.commit()
        return int(cursor.lastrowid)


def finish_debate_turn(
    self: MockMessengerStore,
    *,
    turn_id: int,
    status: str,
    response_text: str | None = None,
    error_text: str | None = None,
) -> None:
    finished_at = _now_ms()
    with self._lock:
        row = self._conn.execute(
            "SELECT started_at FROM debate_turns WHERE id = ?",
            (turn_id,),
        ).fetchone()
        started_at = int(row["started_at"]) if row is not None else finished_at
        duration_ms = max(0, finished_at - started_at)
        self._conn.execute(
            """
            UPDATE debate_turns
            SET status = ?, response_text = ?, error_text = ?, finished_at = ?, duration_ms = ?
            WHERE id = ?
            """,
            (status, response_text, error_text, finished_at, duration_ms, turn_id),
        )
        self._conn.commit()


def finish_debate(
    self: MockMessengerStore,
    *,
    debate_id: str,
    status: str,
    error_summary: str | None = None,
) -> None:
    finished_at = _now_ms()
    with self._lock:
        self._conn.execute(
            """
            UPDATE debates
            SET status = ?, finished_at = ?, error_summary = ?, stop_requested = CASE
              WHEN ? = 'stopped' THEN 1 ELSE stop_requested
            END
            WHERE debate_id = ?
            """,
            (status, finished_at, error_summary, status, debate_id),
        )
        self._conn.commit()


def list_debate_turns(self: MockMessengerStore, *, debate_id: str) -> list[dict[str, Any]]:
    with self._lock:
        rows = self._conn.execute(
            """
            SELECT id, debate_id, round_no, speaker_position, speaker_bot_id, speaker_label,
                   prompt_text, response_text, status, error_text, started_at, finished_at, duration_ms
            FROM debate_turns
            WHERE debate_id = ?
            ORDER BY id ASC
            """,
            (debate_id,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "debate_id": row["debate_id"],
            "round_no": int(row["round_no"]),
            "speaker_position": int(row["speaker_position"]),
            "speaker_bot_id": row["speaker_bot_id"],
            "speaker_label": row["speaker_label"],
            "prompt_text": row["prompt_text"],
            "response_text": row["response_text"],
            "status": row["status"],
            "error_text": row["error_text"],
            "started_at": int(row["started_at"]),
            "finished_at": int(row["finished_at"]) if row["finished_at"] is not None else None,
            "duration_ms": int(row["duration_ms"]) if row["duration_ms"] is not None else None,
        }
        for row in rows
    ]


def list_debate_participants(self: MockMessengerStore, *, debate_id: str) -> list[dict[str, Any]]:
    with self._lock:
        rows = self._conn.execute(
            """
            SELECT id, debate_id, position, profile_id, label, bot_id, token, chat_id, user_id, adapter, created_at
            FROM debate_participants
            WHERE debate_id = ?
            ORDER BY position ASC
            """,
            (debate_id,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "debate_id": row["debate_id"],
            "position": int(row["position"]),
            "profile_id": row["profile_id"],
            "label": row["label"],
            "bot_id": row["bot_id"],
            "token": row["token"],
            "chat_id": self._maybe_int(row["chat_id"]),
            "user_id": self._maybe_int(row["user_id"]),
            "adapter": row["adapter"],
            "created_at": int(row["created_at"]),
        }
        for row in rows
    ]
