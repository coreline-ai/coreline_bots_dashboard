from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from telegram_bot_new.mock_messenger.store import MockMessengerStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def create_cowork(
    self: MockMessengerStore,
    *,
    task: str,
    max_parallel: int,
    max_turn_sec: int,
    fresh_session: bool,
    keep_partial_on_error: bool,
    participants: list[dict[str, Any]],
) -> str:
    cowork_id = uuid.uuid4().hex
    now_ms = _now_ms()
    with self._lock:
        self._conn.execute(
            """
            INSERT INTO coworks(
              cowork_id, task, status, max_parallel, max_turn_sec, fresh_session, keep_partial_on_error,
              stop_requested, budget_floor_sec, budget_applied_sec, budget_auto_raised, budget_reason,
              stop_reason, stop_source, stop_requested_by, last_timeout_event_json,
              created_at, started_at, finished_at, error_summary, final_report_json
            )
            VALUES (?, ?, 'queued', ?, ?, ?, ?, 0, NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL)
            """,
            (
                cowork_id,
                task,
                max_parallel,
                max_turn_sec,
                1 if fresh_session else 0,
                1 if keep_partial_on_error else 0,
                now_ms,
            ),
        )
        for index, participant in enumerate(participants, start=1):
            self._conn.execute(
                """
                INSERT INTO cowork_participants(
                  cowork_id, position, profile_id, label, bot_id, token, chat_id, user_id, role, adapter, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cowork_id,
                    index,
                    str(participant.get("profile_id") or ""),
                    str(participant.get("label") or ""),
                    str(participant.get("bot_id") or ""),
                    str(participant.get("token") or ""),
                    str(participant.get("chat_id") or ""),
                    str(participant.get("user_id") or ""),
                    str(participant.get("role") or "implementer"),
                    str(participant.get("adapter") or "") or None,
                    now_ms,
                ),
            )
        self._conn.commit()
    return cowork_id


def set_cowork_budget(
    self: MockMessengerStore,
    *,
    cowork_id: str,
    budget_floor_sec: int | None,
    budget_applied_sec: int | None,
    budget_auto_raised: bool,
    budget_reason: str | None = None,
) -> None:
    with self._lock:
        self._conn.execute(
            """
            UPDATE coworks
            SET budget_floor_sec = ?, budget_applied_sec = ?, budget_auto_raised = ?, budget_reason = ?
            WHERE cowork_id = ?
            """,
            (
                int(budget_floor_sec) if budget_floor_sec is not None else None,
                int(budget_applied_sec) if budget_applied_sec is not None else None,
                1 if budget_auto_raised else 0,
                budget_reason,
                cowork_id,
            ),
        )
        self._conn.commit()


def set_cowork_running(self: MockMessengerStore, *, cowork_id: str) -> None:
    now_ms = _now_ms()
    with self._lock:
        self._conn.execute(
            """
            UPDATE coworks
            SET status = 'running',
                started_at = COALESCE(started_at, ?)
            WHERE cowork_id = ?
            """,
            (now_ms, cowork_id),
        )
        self._conn.commit()


def set_cowork_stop_requested(
    self: MockMessengerStore,
    *,
    cowork_id: str,
    reason: str | None = None,
    source: str | None = None,
    requested_by: str | None = None,
) -> None:
    with self._lock:
        self._conn.execute(
            """
            UPDATE coworks
            SET stop_requested = 1,
                stop_reason = COALESCE(?, stop_reason),
                stop_source = COALESCE(?, stop_source),
                stop_requested_by = COALESCE(?, stop_requested_by)
            WHERE cowork_id = ?
            """,
            (reason, source, requested_by, cowork_id),
        )
        self._conn.commit()


def set_cowork_timeout_event(self: MockMessengerStore, *, cowork_id: str, event: dict[str, Any] | None) -> None:
    serialized = json.dumps(event, ensure_ascii=False) if isinstance(event, dict) else None
    with self._lock:
        self._conn.execute(
            "UPDATE coworks SET last_timeout_event_json = ? WHERE cowork_id = ?",
            (serialized, cowork_id),
        )
        self._conn.commit()


def get_cowork(self: MockMessengerStore, *, cowork_id: str) -> dict[str, Any] | None:
    with self._lock:
        row = self._conn.execute(
            """
            SELECT cowork_id, task, status, max_parallel, max_turn_sec, fresh_session, keep_partial_on_error,
                   stop_requested, budget_floor_sec, budget_applied_sec, budget_auto_raised, budget_reason,
                   stop_reason, stop_source, stop_requested_by, last_timeout_event_json,
                   created_at, started_at, finished_at, error_summary, final_report_json
            FROM coworks
            WHERE cowork_id = ?
            """,
            (cowork_id,),
        ).fetchone()
    if row is None:
        return None
    return self._row_to_cowork(row)


def get_active_cowork(self: MockMessengerStore) -> dict[str, Any] | None:
    with self._lock:
        row = self._conn.execute(
            """
            SELECT cowork_id, task, status, max_parallel, max_turn_sec, fresh_session, keep_partial_on_error,
                   stop_requested, budget_floor_sec, budget_applied_sec, budget_auto_raised, budget_reason,
                   stop_reason, stop_source, stop_requested_by, last_timeout_event_json,
                   created_at, started_at, finished_at, error_summary, final_report_json
            FROM coworks
            WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    return self._row_to_cowork(row)


def insert_cowork_stage_start(
    self: MockMessengerStore,
    *,
    cowork_id: str,
    stage_no: int,
    stage_type: str,
    actor_bot_id: str,
    actor_label: str,
    actor_role: str,
    prompt_text: str,
) -> int:
    started_at = _now_ms()
    with self._lock:
        cursor = self._conn.execute(
            """
            INSERT INTO cowork_stages(
              cowork_id, stage_no, stage_type, actor_bot_id, actor_label, actor_role,
              prompt_text, response_text, status, error_text, resolved_status,
              raw_outcome_status, raw_outcome_detail, raw_outcome_error_text,
              fallback_applied, fallback_source, effective_timeout_sec,
              started_at, finished_at, duration_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'running', NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, ?, NULL, NULL)
            """,
            (cowork_id, stage_no, stage_type, actor_bot_id, actor_label, actor_role, prompt_text, started_at),
        )
        self._conn.commit()
        return int(cursor.lastrowid)


def finish_cowork_stage(
    self: MockMessengerStore,
    *,
    stage_id: int,
    status: str,
    response_text: str | None = None,
    error_text: str | None = None,
    resolved_status: str | None = None,
    raw_outcome_status: str | None = None,
    raw_outcome_detail: str | None = None,
    raw_outcome_error_text: str | None = None,
    fallback_applied: bool = False,
    fallback_source: str | None = None,
    effective_timeout_sec: int | None = None,
) -> None:
    finished_at = _now_ms()
    with self._lock:
        row = self._conn.execute(
            "SELECT started_at FROM cowork_stages WHERE id = ?",
            (stage_id,),
        ).fetchone()
        started_at = int(row["started_at"]) if row is not None else finished_at
        duration_ms = max(0, finished_at - started_at)
        self._conn.execute(
            """
            UPDATE cowork_stages
            SET status = ?, response_text = ?, error_text = ?, resolved_status = ?, raw_outcome_status = ?,
                raw_outcome_detail = ?, raw_outcome_error_text = ?, fallback_applied = ?, fallback_source = ?,
                effective_timeout_sec = ?, finished_at = ?, duration_ms = ?
            WHERE id = ?
            """,
            (
                status,
                response_text,
                error_text,
                resolved_status or status,
                raw_outcome_status,
                raw_outcome_detail,
                raw_outcome_error_text,
                1 if fallback_applied else 0,
                fallback_source,
                int(effective_timeout_sec) if effective_timeout_sec is not None else None,
                finished_at,
                duration_ms,
                stage_id,
            ),
        )
        self._conn.commit()


def insert_cowork_task(
    self: MockMessengerStore,
    *,
    cowork_id: str,
    task_no: int,
    title: str,
    spec_json: dict[str, Any],
    assignee_bot_id: str,
    assignee_label: str,
    assignee_role: str,
    status: str = "pending",
) -> int:
    with self._lock:
        cursor = self._conn.execute(
            """
            INSERT INTO cowork_tasks(
              cowork_id, task_no, title, spec_json, assignee_bot_id, assignee_label, assignee_role,
              status, response_text, error_text, resolved_status, raw_outcome_status, raw_outcome_detail,
              raw_outcome_error_text, fallback_applied, fallback_source, effective_timeout_sec,
              blocked_by_task_no, blocked_by_bot_id, blocked_by_reason,
              started_at, finished_at, duration_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (
                cowork_id,
                task_no,
                title,
                json.dumps(spec_json, ensure_ascii=False),
                assignee_bot_id,
                assignee_label,
                assignee_role,
                status,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)


def start_cowork_task(self: MockMessengerStore, *, task_id: int) -> None:
    started_at = _now_ms()
    with self._lock:
        self._conn.execute(
            """
            UPDATE cowork_tasks
            SET status = 'running', started_at = COALESCE(started_at, ?)
            WHERE id = ?
            """,
            (started_at, task_id),
        )
        self._conn.commit()


def finish_cowork_task(
    self: MockMessengerStore,
    *,
    task_id: int,
    status: str,
    response_text: str | None = None,
    error_text: str | None = None,
    resolved_status: str | None = None,
    raw_outcome_status: str | None = None,
    raw_outcome_detail: str | None = None,
    raw_outcome_error_text: str | None = None,
    fallback_applied: bool = False,
    fallback_source: str | None = None,
    effective_timeout_sec: int | None = None,
    blocked_by_task_no: int | None = None,
    blocked_by_bot_id: str | None = None,
    blocked_by_reason: str | None = None,
) -> None:
    finished_at = _now_ms()
    with self._lock:
        row = self._conn.execute(
            "SELECT started_at FROM cowork_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        started_at = int(row["started_at"]) if row is not None and row["started_at"] is not None else finished_at
        duration_ms = max(0, finished_at - started_at)
        self._conn.execute(
            """
            UPDATE cowork_tasks
            SET status = ?, response_text = ?, error_text = ?, resolved_status = ?, raw_outcome_status = ?,
                raw_outcome_detail = ?, raw_outcome_error_text = ?, fallback_applied = ?, fallback_source = ?,
                effective_timeout_sec = ?, blocked_by_task_no = ?, blocked_by_bot_id = ?, blocked_by_reason = ?,
                finished_at = ?, duration_ms = ?
            WHERE id = ?
            """,
            (
                status,
                response_text,
                error_text,
                resolved_status or status,
                raw_outcome_status,
                raw_outcome_detail,
                raw_outcome_error_text,
                1 if fallback_applied else 0,
                fallback_source,
                int(effective_timeout_sec) if effective_timeout_sec is not None else None,
                int(blocked_by_task_no) if blocked_by_task_no is not None else None,
                blocked_by_bot_id,
                blocked_by_reason,
                finished_at,
                duration_ms,
                task_id,
            ),
        )
        self._conn.commit()


def finish_cowork(
    self: MockMessengerStore,
    *,
    cowork_id: str,
    status: str,
    error_summary: str | None = None,
    final_report: dict[str, Any] | None = None,
) -> None:
    finished_at = _now_ms()
    serialized_report = json.dumps(final_report, ensure_ascii=False) if isinstance(final_report, dict) else None
    with self._lock:
        self._conn.execute(
            """
            UPDATE coworks
            SET status = ?, finished_at = ?, error_summary = ?, final_report_json = ?, stop_requested = CASE
              WHEN ? = 'stopped' THEN 1 ELSE stop_requested
            END
            WHERE cowork_id = ?
            """,
            (status, finished_at, error_summary, serialized_report, status, cowork_id),
        )
        self._conn.commit()


def list_cowork_participants(self: MockMessengerStore, *, cowork_id: str) -> list[dict[str, Any]]:
    with self._lock:
        rows = self._conn.execute(
            """
            SELECT id, cowork_id, position, profile_id, label, bot_id, token, chat_id, user_id, role, adapter, created_at
            FROM cowork_participants
            WHERE cowork_id = ?
            ORDER BY position ASC
            """,
            (cowork_id,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "cowork_id": row["cowork_id"],
            "position": int(row["position"]),
            "profile_id": row["profile_id"],
            "label": row["label"],
            "bot_id": row["bot_id"],
            "token": row["token"],
            "chat_id": self._maybe_int(row["chat_id"]),
            "user_id": self._maybe_int(row["user_id"]),
            "role": row["role"],
            "adapter": row["adapter"],
            "created_at": int(row["created_at"]),
        }
        for row in rows
    ]


def list_cowork_stages(self: MockMessengerStore, *, cowork_id: str) -> list[dict[str, Any]]:
    with self._lock:
        rows = self._conn.execute(
            """
            SELECT id, cowork_id, stage_no, stage_type, actor_bot_id, actor_label, actor_role,
                   prompt_text, response_text, status, error_text, resolved_status, raw_outcome_status,
                   raw_outcome_detail, raw_outcome_error_text, fallback_applied, fallback_source,
                   effective_timeout_sec, started_at, finished_at, duration_ms
            FROM cowork_stages
            WHERE cowork_id = ?
            ORDER BY id ASC
            """,
            (cowork_id,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "cowork_id": row["cowork_id"],
            "stage_no": int(row["stage_no"]),
            "stage_type": row["stage_type"],
            "actor_bot_id": row["actor_bot_id"],
            "actor_label": row["actor_label"],
            "actor_role": row["actor_role"],
            "prompt_text": row["prompt_text"],
            "response_text": row["response_text"],
            "status": row["status"],
            "error_text": row["error_text"],
            "resolved_status": row["resolved_status"],
            "raw_outcome_status": row["raw_outcome_status"],
            "raw_outcome_detail": row["raw_outcome_detail"],
            "raw_outcome_error_text": row["raw_outcome_error_text"],
            "fallback_applied": bool(int(row["fallback_applied"])) if row["fallback_applied"] is not None else False,
            "fallback_source": row["fallback_source"],
            "effective_timeout_sec": int(row["effective_timeout_sec"]) if row["effective_timeout_sec"] is not None else None,
            "started_at": int(row["started_at"]),
            "finished_at": int(row["finished_at"]) if row["finished_at"] is not None else None,
            "duration_ms": int(row["duration_ms"]) if row["duration_ms"] is not None else None,
        }
        for row in rows
    ]


def list_cowork_tasks(self: MockMessengerStore, *, cowork_id: str) -> list[dict[str, Any]]:
    with self._lock:
        rows = self._conn.execute(
            """
            SELECT id, cowork_id, task_no, title, spec_json, assignee_bot_id, assignee_label, assignee_role,
                   status, response_text, error_text, resolved_status, raw_outcome_status, raw_outcome_detail,
                   raw_outcome_error_text, fallback_applied, fallback_source, effective_timeout_sec,
                   blocked_by_task_no, blocked_by_bot_id, blocked_by_reason,
                   started_at, finished_at, duration_ms
            FROM cowork_tasks
            WHERE cowork_id = ?
            ORDER BY task_no ASC, id ASC
            """,
            (cowork_id,),
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        spec = {}
        raw_spec = row["spec_json"]
        if isinstance(raw_spec, str) and raw_spec:
            try:
                loaded = json.loads(raw_spec)
                if isinstance(loaded, dict):
                    spec = loaded
            except Exception:
                spec = {}
        results.append(
            {
                "id": int(row["id"]),
                "cowork_id": row["cowork_id"],
                "task_no": int(row["task_no"]),
                "title": row["title"],
                "spec_json": spec,
                "assignee_bot_id": row["assignee_bot_id"],
                "assignee_label": row["assignee_label"],
                "assignee_role": row["assignee_role"],
                "status": row["status"],
                "response_text": row["response_text"],
                "error_text": row["error_text"],
                "resolved_status": row["resolved_status"],
                "raw_outcome_status": row["raw_outcome_status"],
                "raw_outcome_detail": row["raw_outcome_detail"],
                "raw_outcome_error_text": row["raw_outcome_error_text"],
                "fallback_applied": bool(int(row["fallback_applied"])) if row["fallback_applied"] is not None else False,
                "fallback_source": row["fallback_source"],
                "effective_timeout_sec": int(row["effective_timeout_sec"]) if row["effective_timeout_sec"] is not None else None,
                "blocked_by_task_no": int(row["blocked_by_task_no"]) if row["blocked_by_task_no"] is not None else None,
                "blocked_by_bot_id": row["blocked_by_bot_id"],
                "blocked_by_reason": row["blocked_by_reason"],
                "started_at": int(row["started_at"]) if row["started_at"] is not None else None,
                "finished_at": int(row["finished_at"]) if row["finished_at"] is not None else None,
                "duration_ms": int(row["duration_ms"]) if row["duration_ms"] is not None else None,
            }
        )
    return results
