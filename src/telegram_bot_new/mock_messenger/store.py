from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_sec() -> int:
    return int(time.time())


class MockMessengerStore:
    def __init__(self, *, db_path: str, data_dir: str) -> None:
        self._lock = threading.Lock()
        self._db_path = db_path
        self._data_dir = Path(data_dir)
        self._documents_dir = self._data_dir / "documents"
        self._documents_dir.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bots (
                  token TEXT PRIMARY KEY,
                  webhook_url TEXT,
                  webhook_secret TEXT,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS updates (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  token TEXT NOT NULL,
                  update_id INTEGER NOT NULL,
                  chat_id TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  delivery_mode TEXT NOT NULL,
                  delivered INTEGER NOT NULL DEFAULT 0,
                  created_at INTEGER NOT NULL,
                  UNIQUE(token, update_id)
                );

                CREATE TABLE IF NOT EXISTS update_counters (
                  token TEXT PRIMARY KEY,
                  last_update_id INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  token TEXT NOT NULL,
                  chat_id TEXT NOT NULL,
                  message_id INTEGER NOT NULL,
                  direction TEXT NOT NULL,
                  text TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  UNIQUE(token, chat_id, message_id)
                );

                CREATE TABLE IF NOT EXISTS callback_answers (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  token TEXT NOT NULL,
                  callback_query_id TEXT NOT NULL,
                  text TEXT,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  token TEXT NOT NULL,
                  chat_id TEXT NOT NULL,
                  message_id INTEGER NOT NULL,
                  filename TEXT NOT NULL,
                  path TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rate_limits (
                  token TEXT NOT NULL,
                  method TEXT NOT NULL,
                  remaining INTEGER NOT NULL,
                  retry_after INTEGER NOT NULL,
                  PRIMARY KEY(token, method)
                );

                CREATE TABLE IF NOT EXISTS debates (
                  debate_id TEXT PRIMARY KEY,
                  scope_key TEXT,
                  topic TEXT NOT NULL,
                  status TEXT NOT NULL,
                  rounds_total INTEGER NOT NULL,
                  max_turn_sec INTEGER NOT NULL,
                  fresh_session INTEGER NOT NULL,
                  stop_requested INTEGER NOT NULL DEFAULT 0,
                  created_at INTEGER NOT NULL,
                  started_at INTEGER,
                  finished_at INTEGER,
                  error_summary TEXT
                );

                CREATE TABLE IF NOT EXISTS debate_participants (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  debate_id TEXT NOT NULL,
                  position INTEGER NOT NULL,
                  profile_id TEXT NOT NULL,
                  label TEXT NOT NULL,
                  bot_id TEXT NOT NULL,
                  token TEXT NOT NULL,
                  chat_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  adapter TEXT,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS debate_turns (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  debate_id TEXT NOT NULL,
                  round_no INTEGER NOT NULL,
                  speaker_position INTEGER NOT NULL,
                  speaker_bot_id TEXT NOT NULL,
                  speaker_label TEXT NOT NULL,
                  prompt_text TEXT NOT NULL,
                  response_text TEXT,
                  status TEXT NOT NULL,
                  error_text TEXT,
                  started_at INTEGER NOT NULL,
                  finished_at INTEGER,
                  duration_ms INTEGER
                );

                CREATE TABLE IF NOT EXISTS coworks (
                  cowork_id TEXT PRIMARY KEY,
                  task TEXT NOT NULL,
                  status TEXT NOT NULL,
                  max_parallel INTEGER NOT NULL,
                  max_turn_sec INTEGER NOT NULL,
                  fresh_session INTEGER NOT NULL,
                  keep_partial_on_error INTEGER NOT NULL,
                  stop_requested INTEGER NOT NULL DEFAULT 0,
                  created_at INTEGER NOT NULL,
                  started_at INTEGER,
                  finished_at INTEGER,
                  error_summary TEXT,
                  final_report_json TEXT
                );

                CREATE TABLE IF NOT EXISTS cowork_participants (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cowork_id TEXT NOT NULL,
                  position INTEGER NOT NULL,
                  profile_id TEXT NOT NULL,
                  label TEXT NOT NULL,
                  bot_id TEXT NOT NULL,
                  token TEXT NOT NULL,
                  chat_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  adapter TEXT,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cowork_stages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cowork_id TEXT NOT NULL,
                  stage_no INTEGER NOT NULL,
                  stage_type TEXT NOT NULL,
                  actor_bot_id TEXT NOT NULL,
                  actor_label TEXT NOT NULL,
                  actor_role TEXT NOT NULL,
                  prompt_text TEXT NOT NULL,
                  response_text TEXT,
                  status TEXT NOT NULL,
                  error_text TEXT,
                  started_at INTEGER NOT NULL,
                  finished_at INTEGER,
                  duration_ms INTEGER
                );

                CREATE TABLE IF NOT EXISTS cowork_tasks (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  cowork_id TEXT NOT NULL,
                  task_no INTEGER NOT NULL,
                  title TEXT NOT NULL,
                  spec_json TEXT NOT NULL,
                  assignee_bot_id TEXT NOT NULL,
                  assignee_label TEXT NOT NULL,
                  assignee_role TEXT NOT NULL,
                  status TEXT NOT NULL,
                  response_text TEXT,
                  error_text TEXT,
                  started_at INTEGER,
                  finished_at INTEGER,
                  duration_ms INTEGER
                );
                """
            )
            self._ensure_column_locked(table="debates", column="scope_key", definition="scope_key TEXT")
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_debates_scope_status_created
                ON debates(scope_key, status, created_at DESC)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_coworks_status_created
                ON coworks(status, created_at DESC)
                """
            )
            self._conn.commit()

    def _ensure_column_locked(self, *, table: str, column: str, definition: str) -> None:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column in existing:
            return
        self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def ensure_bot(self, token: str) -> None:
        now = _now_ms()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bots(token, webhook_url, webhook_secret, created_at, updated_at)
                VALUES (?, NULL, NULL, ?, ?)
                ON CONFLICT(token) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (token, now, now),
            )
            self._conn.commit()

    def get_bot(self, token: str) -> dict[str, Any]:
        self.ensure_bot(token)
        with self._lock:
            row = self._conn.execute(
                "SELECT token, webhook_url, webhook_secret, created_at, updated_at FROM bots WHERE token = ?",
                (token,),
            ).fetchone()
        assert row is not None
        return dict(row)

    def set_webhook(self, *, token: str, url: str, secret_token: str | None, drop_pending_updates: bool) -> None:
        self.ensure_bot(token)
        now = _now_ms()
        with self._lock:
            self._conn.execute(
                """
                UPDATE bots
                SET webhook_url = ?, webhook_secret = ?, updated_at = ?
                WHERE token = ?
                """,
                (url, secret_token, now, token),
            )
            if drop_pending_updates:
                self._conn.execute(
                    "UPDATE updates SET delivered = 1 WHERE token = ? AND delivered = 0",
                    (token,),
                )
            self._conn.commit()

    def delete_webhook(self, *, token: str, drop_pending_updates: bool) -> None:
        self.ensure_bot(token)
        now = _now_ms()
        with self._lock:
            self._conn.execute(
                """
                UPDATE bots
                SET webhook_url = NULL, webhook_secret = NULL, updated_at = ?
                WHERE token = ?
                """,
                (now, token),
            )
            if drop_pending_updates:
                self._conn.execute(
                    "UPDATE updates SET delivered = 1 WHERE token = ? AND delivered = 0",
                    (token,),
                )
            self._conn.commit()

    def enqueue_user_message(self, *, token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        self.ensure_bot(token)
        chat_key = str(chat_id)
        now_ms = _now_ms()
        now_sec = _now_sec()

        with self._lock:
            message_id = self._next_message_id_locked(token=token, chat_id=chat_key)
            self._conn.execute(
                """
                INSERT INTO messages(token, chat_id, message_id, direction, text, created_at, updated_at)
                VALUES (?, ?, ?, 'user', ?, ?, ?)
                """,
                (token, chat_key, message_id, text, now_ms, now_ms),
            )

            update_id = self._next_update_id_locked(token=token)
            payload = {
                "update_id": update_id,
                "message": {
                    "message_id": message_id,
                    "date": now_sec,
                    "chat": {"id": chat_id, "type": "private"},
                    "from": {"id": user_id, "is_bot": False, "first_name": "MockUser"},
                    "text": text,
                },
            }

            bot_row = self._conn.execute(
                "SELECT webhook_url, webhook_secret FROM bots WHERE token = ?",
                (token,),
            ).fetchone()
            assert bot_row is not None
            webhook_url = bot_row["webhook_url"]
            webhook_secret = bot_row["webhook_secret"]
            delivery_mode = "webhook" if webhook_url else "polling"

            self._conn.execute(
                """
                INSERT INTO updates(token, update_id, chat_id, payload_json, delivery_mode, delivered, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (token, update_id, chat_key, json.dumps(payload, ensure_ascii=False), delivery_mode, now_ms),
            )
            self._conn.commit()

        return {
            "token": token,
            "chat_id": chat_id,
            "update_id": update_id,
            "payload": payload,
            "delivery_mode": delivery_mode,
            "webhook_url": webhook_url,
            "webhook_secret": webhook_secret,
        }

    def fetch_updates(
        self,
        *,
        token: str,
        offset: int | None,
        limit: int,
        allow_get_updates_with_webhook: bool,
    ) -> list[dict[str, Any]]:
        bot = self.get_bot(token)
        if bot.get("webhook_url") and not allow_get_updates_with_webhook:
            return []

        query = [
            "SELECT update_id, payload_json",
            "FROM updates",
            "WHERE token = ? AND delivered = 0",
        ]
        params: list[Any] = [token]
        if offset is not None:
            query.append("AND update_id >= ?")
            params.append(offset)
        query.append("ORDER BY update_id ASC LIMIT ?")
        params.append(limit)

        with self._lock:
            rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
            if not rows:
                return []

            update_ids = [int(row["update_id"]) for row in rows]
            placeholders = ", ".join("?" for _ in update_ids)
            self._conn.execute(
                f"UPDATE updates SET delivered = 1 WHERE token = ? AND update_id IN ({placeholders})",
                (token, *update_ids),
            )
            self._conn.commit()

        return [json.loads(row["payload_json"]) for row in rows]

    def mark_update_delivered(self, *, token: str, update_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE updates SET delivered = 1 WHERE token = ? AND update_id = ?",
                (token, update_id),
            )
            self._conn.commit()

    def store_bot_message(self, *, token: str, chat_id: int, text: str) -> dict[str, Any]:
        self.ensure_bot(token)
        now_ms = _now_ms()
        chat_key = str(chat_id)
        with self._lock:
            message_id = self._next_message_id_locked(token=token, chat_id=chat_key)
            self._conn.execute(
                """
                INSERT INTO messages(token, chat_id, message_id, direction, text, created_at, updated_at)
                VALUES (?, ?, ?, 'bot', ?, ?, ?)
                """,
                (token, chat_key, message_id, text, now_ms, now_ms),
            )
            self._conn.commit()
        return self._build_message_payload(chat_id=chat_id, message_id=message_id, text=text)

    def edit_bot_message(self, *, token: str, chat_id: int, message_id: int, text: str) -> dict[str, Any] | None:
        now_ms = _now_ms()
        chat_key = str(chat_id)
        with self._lock:
            found = self._conn.execute(
                """
                SELECT id
                FROM messages
                WHERE token = ? AND chat_id = ? AND message_id = ? AND direction = 'bot'
                """,
                (token, chat_key, message_id),
            ).fetchone()
            if found is None:
                return None
            self._conn.execute(
                """
                UPDATE messages
                SET text = ?, updated_at = ?
                WHERE token = ? AND chat_id = ? AND message_id = ? AND direction = 'bot'
                """,
                (text, now_ms, token, chat_key, message_id),
            )
            self._conn.commit()
        return self._build_message_payload(chat_id=chat_id, message_id=message_id, text=text)

    def record_callback_answer(self, *, token: str, callback_query_id: str, text: str | None) -> None:
        self.ensure_bot(token)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO callback_answers(token, callback_query_id, text, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token, callback_query_id, text, _now_ms()),
            )
            self._conn.commit()

    def store_document(
        self,
        *,
        token: str,
        chat_id: int,
        filename: str,
        content: bytes,
        caption: str | None,
    ) -> dict[str, Any]:
        self.ensure_bot(token)
        now_ms = _now_ms()
        now_sec = _now_sec()
        chat_key = str(chat_id)
        safe_token = self._safe_name(token)
        safe_filename = self._safe_name(filename)
        token_dir = self._documents_dir / safe_token
        token_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            message_id = self._next_message_id_locked(token=token, chat_id=chat_key)
            stored_name = f"{now_ms}_{message_id}_{safe_filename}"
            stored_path = token_dir / stored_name
            stored_path.write_bytes(content)

            text = caption or f"[document] {filename}"
            self._conn.execute(
                """
                INSERT INTO messages(token, chat_id, message_id, direction, text, created_at, updated_at)
                VALUES (?, ?, ?, 'bot', ?, ?, ?)
                """,
                (token, chat_key, message_id, text, now_ms, now_ms),
            )
            self._conn.execute(
                """
                INSERT INTO documents(token, chat_id, message_id, filename, path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token, chat_key, message_id, filename, str(stored_path), now_ms),
            )
            self._conn.commit()

        return {
            "message_id": message_id,
            "date": now_sec,
            "chat": {"id": chat_id, "type": "private"},
            "caption": caption,
            "document": {
                "file_name": filename,
                "file_unique_id": f"mock-{token}-{message_id}",
                "file_size": len(content),
            },
        }

    def list_threads(self, *, token: str | None = None) -> list[dict[str, Any]]:
        query = [
            "SELECT m.token, m.chat_id, COUNT(*) AS message_count, MAX(m.updated_at) AS last_updated_at, b.webhook_url",
            "FROM messages m",
            "LEFT JOIN bots b ON b.token = m.token",
        ]
        params: list[Any] = []
        if token:
            query.append("WHERE m.token = ?")
            params.append(token)
        query.append("GROUP BY m.token, m.chat_id, b.webhook_url")
        query.append("ORDER BY last_updated_at DESC")

        with self._lock:
            rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
        return [
            {
                "token": row["token"],
                "chat_id": int(row["chat_id"]) if str(row["chat_id"]).isdigit() else row["chat_id"],
                "message_count": int(row["message_count"]),
                "last_updated_at": int(row["last_updated_at"]),
                "webhook_enabled": bool(row["webhook_url"]),
            }
            for row in rows
        ]

    def clear_messages(self, *, token: str, chat_id: int | None = None) -> dict[str, int]:
        chat_key = str(chat_id) if chat_id is not None else None
        query = [
            "SELECT id, path",
            "FROM documents",
            "WHERE token = ?",
        ]
        params: list[Any] = [token]
        if chat_key is not None:
            query.append("AND chat_id = ?")
            params.append(chat_key)

        with self._lock:
            doc_rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
            file_paths = [str(row["path"]) for row in doc_rows if row["path"]]

            if chat_key is None:
                deleted_docs = self._conn.execute(
                    "DELETE FROM documents WHERE token = ?",
                    (token,),
                ).rowcount
                deleted_messages = self._conn.execute(
                    "DELETE FROM messages WHERE token = ?",
                    (token,),
                ).rowcount
                deleted_updates = self._conn.execute(
                    "DELETE FROM updates WHERE token = ?",
                    (token,),
                ).rowcount
            else:
                deleted_docs = self._conn.execute(
                    "DELETE FROM documents WHERE token = ? AND chat_id = ?",
                    (token, chat_key),
                ).rowcount
                deleted_messages = self._conn.execute(
                    "DELETE FROM messages WHERE token = ? AND chat_id = ?",
                    (token, chat_key),
                ).rowcount
                deleted_updates = self._conn.execute(
                    "DELETE FROM updates WHERE token = ? AND chat_id = ?",
                    (token, chat_key),
                ).rowcount
            self._conn.commit()

        removed_files = 0
        for path in file_paths:
            try:
                os.remove(path)
                removed_files += 1
            except FileNotFoundError:
                continue
            except OSError:
                continue

        return {
            "deleted_messages": int(deleted_messages or 0),
            "deleted_documents": int(deleted_docs or 0),
            "deleted_updates": int(deleted_updates or 0),
            "removed_files": removed_files,
        }

    def get_messages(self, *, token: str, chat_id: int | None, limit: int) -> list[dict[str, Any]]:
        query = [
            "SELECT token, chat_id, message_id, direction, text, created_at, updated_at",
            "FROM messages",
            "WHERE token = ?",
        ]
        params: list[Any] = [token]
        if chat_id is not None:
            query.append("AND chat_id = ?")
            params.append(str(chat_id))
        query.append("ORDER BY created_at DESC LIMIT ?")
        params.append(limit)

        with self._lock:
            rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
            message_ids = [int(row["message_id"]) for row in rows]
            documents_map: dict[tuple[str, int], dict[str, Any]] = {}
            if message_ids:
                docs_query = [
                    "SELECT id, token, chat_id, message_id, filename, path, created_at",
                    "FROM documents",
                    "WHERE token = ?",
                ]
                docs_params: list[Any] = [token]
                if chat_id is not None:
                    docs_query.append("AND chat_id = ?")
                    docs_params.append(str(chat_id))
                placeholders = ", ".join("?" for _ in message_ids)
                docs_query.append(f"AND message_id IN ({placeholders})")
                docs_params.extend(message_ids)
                docs_rows = self._conn.execute("\n".join(docs_query), tuple(docs_params)).fetchall()
                for doc in docs_rows:
                    media_type = self._guess_media_type(doc["filename"])
                    documents_map[(str(doc["chat_id"]), int(doc["message_id"]))] = {
                        "id": int(doc["id"]),
                        "filename": doc["filename"],
                        "media_type": media_type,
                        "is_image": media_type.startswith("image/"),
                        "is_html": media_type == "text/html",
                        "created_at": int(doc["created_at"]),
                    }
        rows = list(reversed(rows))
        return [
            {
                "token": row["token"],
                "chat_id": int(row["chat_id"]) if str(row["chat_id"]).isdigit() else row["chat_id"],
                "message_id": int(row["message_id"]),
                "direction": row["direction"],
                "text": row["text"],
                "created_at": int(row["created_at"]),
                "updated_at": int(row["updated_at"]),
                "document": documents_map.get((str(row["chat_id"]), int(row["message_id"]))),
            }
            for row in rows
        ]

    def get_document_file(self, *, token: str, document_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, token, filename, path, created_at
                FROM documents
                WHERE id = ? AND token = ?
                """,
                (document_id, token),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "token": row["token"],
            "filename": row["filename"],
            "path": row["path"],
            "media_type": self._guess_media_type(row["filename"]),
            "created_at": int(row["created_at"]),
        }

    def get_recent_updates(self, *, token: str, chat_id: int | None, limit: int) -> list[dict[str, Any]]:
        query = [
            "SELECT update_id, chat_id, delivery_mode, delivered, created_at",
            "FROM updates",
            "WHERE token = ?",
        ]
        params: list[Any] = [token]
        if chat_id is not None:
            query.append("AND chat_id = ?")
            params.append(str(chat_id))
        query.append("ORDER BY update_id DESC LIMIT ?")
        params.append(limit)

        with self._lock:
            rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
        rows = list(reversed(rows))
        return [
            {
                "update_id": int(row["update_id"]),
                "chat_id": int(row["chat_id"]) if str(row["chat_id"]).isdigit() else row["chat_id"],
                "delivery_mode": row["delivery_mode"],
                "delivered": bool(row["delivered"]),
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]

    def get_state(self, *, token: str | None = None) -> dict[str, Any]:
        with self._lock:
            if token:
                bots = self._conn.execute(
                    "SELECT token, webhook_url, webhook_secret, updated_at FROM bots WHERE token = ?",
                    (token,),
                ).fetchall()
                updates_count = self._conn.execute(
                    "SELECT COUNT(*) FROM updates WHERE token = ?",
                    (token,),
                ).fetchone()[0]
                undelivered_count = self._conn.execute(
                    "SELECT COUNT(*) FROM updates WHERE token = ? AND delivered = 0",
                    (token,),
                ).fetchone()[0]
                messages_count = self._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE token = ?",
                    (token,),
                ).fetchone()[0]
            else:
                bots = self._conn.execute(
                    "SELECT token, webhook_url, webhook_secret, updated_at FROM bots ORDER BY token ASC"
                ).fetchall()
                updates_count = self._conn.execute("SELECT COUNT(*) FROM updates").fetchone()[0]
                undelivered_count = self._conn.execute(
                    "SELECT COUNT(*) FROM updates WHERE delivered = 0"
                ).fetchone()[0]
                messages_count = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

        return {
            "bots": [
                {
                    "token": row["token"],
                    "webhook_url": row["webhook_url"],
                    "webhook_secret": row["webhook_secret"],
                    "updated_at": int(row["updated_at"]),
                }
                for row in bots
            ],
            "updates_total": int(updates_count),
            "updates_undelivered": int(undelivered_count),
            "messages_total": int(messages_count),
        }

    def set_rate_limit_rule(self, *, token: str, method: str, count: int, retry_after: int) -> None:
        self.ensure_bot(token)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO rate_limits(token, method, remaining, retry_after)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(token, method) DO UPDATE
                SET remaining = excluded.remaining, retry_after = excluded.retry_after
                """,
                (token, method, count, retry_after),
            )
            self._conn.commit()

    def consume_rate_limit(self, *, token: str, method: str) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT remaining, retry_after FROM rate_limits WHERE token = ? AND method = ?",
                (token, method),
            ).fetchone()
            if row is None:
                return None
            remaining = int(row["remaining"])
            retry_after = int(row["retry_after"])
            if remaining <= 0:
                return None
            self._conn.execute(
                """
                UPDATE rate_limits
                SET remaining = CASE WHEN remaining > 0 THEN remaining - 1 ELSE 0 END
                WHERE token = ? AND method = ?
                """,
                (token, method),
            )
            self._conn.commit()
            return retry_after

    def create_debate(
        self,
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

    def set_debate_running(self, *, debate_id: str) -> None:
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

    def set_debate_stop_requested(self, *, debate_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE debates SET stop_requested = 1 WHERE debate_id = ?",
                (debate_id,),
            )
            self._conn.commit()

    def get_debate(self, *, debate_id: str) -> dict[str, Any] | None:
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

    def get_active_debate(self, *, scope_key: str | None = None) -> dict[str, Any] | None:
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
        self,
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
        self,
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
        self,
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

    def list_debate_turns(self, *, debate_id: str) -> list[dict[str, Any]]:
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

    def list_debate_participants(self, *, debate_id: str) -> list[dict[str, Any]]:
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

    def create_cowork(
        self,
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
                  stop_requested, created_at, started_at, finished_at, error_summary, final_report_json
                )
                VALUES (?, ?, 'queued', ?, ?, ?, ?, 0, ?, NULL, NULL, NULL, NULL)
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

    def set_cowork_running(self, *, cowork_id: str) -> None:
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

    def set_cowork_stop_requested(self, *, cowork_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE coworks SET stop_requested = 1 WHERE cowork_id = ?",
                (cowork_id,),
            )
            self._conn.commit()

    def get_cowork(self, *, cowork_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT cowork_id, task, status, max_parallel, max_turn_sec, fresh_session, keep_partial_on_error,
                       stop_requested, created_at, started_at, finished_at, error_summary, final_report_json
                FROM coworks
                WHERE cowork_id = ?
                """,
                (cowork_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_cowork(row)

    def get_active_cowork(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT cowork_id, task, status, max_parallel, max_turn_sec, fresh_session, keep_partial_on_error,
                       stop_requested, created_at, started_at, finished_at, error_summary, final_report_json
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
        self,
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
                  prompt_text, response_text, status, error_text, started_at, finished_at, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'running', NULL, ?, NULL, NULL)
                """,
                (cowork_id, stage_no, stage_type, actor_bot_id, actor_label, actor_role, prompt_text, started_at),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def finish_cowork_stage(
        self,
        *,
        stage_id: int,
        status: str,
        response_text: str | None = None,
        error_text: str | None = None,
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
                SET status = ?, response_text = ?, error_text = ?, finished_at = ?, duration_ms = ?
                WHERE id = ?
                """,
                (status, response_text, error_text, finished_at, duration_ms, stage_id),
            )
            self._conn.commit()

    def insert_cowork_task(
        self,
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
                  status, response_text, error_text, started_at, finished_at, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
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

    def start_cowork_task(self, *, task_id: int) -> None:
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
        self,
        *,
        task_id: int,
        status: str,
        response_text: str | None = None,
        error_text: str | None = None,
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
                SET status = ?, response_text = ?, error_text = ?, finished_at = ?, duration_ms = ?
                WHERE id = ?
                """,
                (status, response_text, error_text, finished_at, duration_ms, task_id),
            )
            self._conn.commit()

    def finish_cowork(
        self,
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

    def list_cowork_participants(self, *, cowork_id: str) -> list[dict[str, Any]]:
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

    def list_cowork_stages(self, *, cowork_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, cowork_id, stage_no, stage_type, actor_bot_id, actor_label, actor_role,
                       prompt_text, response_text, status, error_text, started_at, finished_at, duration_ms
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
                "started_at": int(row["started_at"]),
                "finished_at": int(row["finished_at"]) if row["finished_at"] is not None else None,
                "duration_ms": int(row["duration_ms"]) if row["duration_ms"] is not None else None,
            }
            for row in rows
        ]

    def list_cowork_tasks(self, *, cowork_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, cowork_id, task_no, title, spec_json, assignee_bot_id, assignee_label, assignee_role,
                       status, response_text, error_text, started_at, finished_at, duration_ms
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
                    "started_at": int(row["started_at"]) if row["started_at"] is not None else None,
                    "finished_at": int(row["finished_at"]) if row["finished_at"] is not None else None,
                    "duration_ms": int(row["duration_ms"]) if row["duration_ms"] is not None else None,
                }
            )
        return results

    def _next_update_id_locked(self, *, token: str) -> int:
        now_ms = _now_ms()
        counter_row = self._conn.execute(
            "SELECT last_update_id FROM update_counters WHERE token = ?",
            (token,),
        ).fetchone()
        max_row = self._conn.execute(
            "SELECT COALESCE(MAX(update_id), 0) AS max_update_id FROM updates WHERE token = ?",
            (token,),
        ).fetchone()
        max_seen = int(max_row["max_update_id"])
        if counter_row is None:
            # Keep update_id monotonic even if timeline rows were deleted.
            seed = max(max_seen, now_ms)
        else:
            # Defend against stale/restored DB counters falling behind runtime offsets.
            seed = max(int(counter_row["last_update_id"]), max_seen, now_ms)

        next_id = seed + 1
        self._conn.execute(
            """
            INSERT INTO update_counters(token, last_update_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(token) DO UPDATE
            SET last_update_id = excluded.last_update_id,
                updated_at = excluded.updated_at
            """,
            (token, next_id, now_ms),
        )
        return next_id

    def _next_message_id_locked(self, *, token: str, chat_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT COALESCE(MAX(message_id), 0) AS max_message_id
            FROM messages
            WHERE token = ? AND chat_id = ?
            """,
            (token, chat_id),
        ).fetchone()
        return int(row["max_message_id"]) + 1

    def _build_message_payload(self, *, chat_id: int, message_id: int, text: str) -> dict[str, Any]:
        return {
            "message_id": message_id,
            "date": _now_sec(),
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        }

    def _row_to_debate(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "debate_id": row["debate_id"],
            "scope_key": row["scope_key"],
            "topic": row["topic"],
            "status": row["status"],
            "rounds_total": int(row["rounds_total"]),
            "max_turn_sec": int(row["max_turn_sec"]),
            "fresh_session": bool(int(row["fresh_session"])),
            "stop_requested": bool(int(row["stop_requested"])),
            "created_at": int(row["created_at"]),
            "started_at": int(row["started_at"]) if row["started_at"] is not None else None,
            "finished_at": int(row["finished_at"]) if row["finished_at"] is not None else None,
            "error_summary": row["error_summary"],
        }

    def _row_to_cowork(self, row: sqlite3.Row) -> dict[str, Any]:
        final_report: dict[str, Any] | None = None
        raw_report = row["final_report_json"]
        if isinstance(raw_report, str) and raw_report:
            try:
                loaded = json.loads(raw_report)
                if isinstance(loaded, dict):
                    final_report = loaded
            except Exception:
                final_report = None
        return {
            "cowork_id": row["cowork_id"],
            "task": row["task"],
            "status": row["status"],
            "max_parallel": int(row["max_parallel"]),
            "max_turn_sec": int(row["max_turn_sec"]),
            "fresh_session": bool(int(row["fresh_session"])),
            "keep_partial_on_error": bool(int(row["keep_partial_on_error"])),
            "stop_requested": bool(int(row["stop_requested"])),
            "created_at": int(row["created_at"]),
            "started_at": int(row["started_at"]) if row["started_at"] is not None else None,
            "finished_at": int(row["finished_at"]) if row["finished_at"] is not None else None,
            "error_summary": row["error_summary"],
            "final_report": final_report,
        }

    @staticmethod
    def _maybe_int(value: Any) -> int | str:
        text = str(value)
        return int(text) if text.lstrip("-").isdigit() else text

    @staticmethod
    def _safe_name(value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
        return sanitized or "value"

    @staticmethod
    def _guess_media_type(filename: str) -> str:
        lower = filename.lower()
        if lower.endswith(".html") or lower.endswith(".htm"):
            return "text/html"
        if lower.endswith(".css"):
            return "text/css"
        if lower.endswith(".js"):
            return "application/javascript"
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return "image/jpeg"
        if lower.endswith(".gif"):
            return "image/gif"
        if lower.endswith(".webp"):
            return "image/webp"
        if lower.endswith(".bmp"):
            return "image/bmp"
        if lower.endswith(".svg"):
            return "image/svg+xml"
        return "application/octet-stream"


from telegram_bot_new.mock_messenger.stores import cowork_store as _cowork_store
from telegram_bot_new.mock_messenger.stores import debate_store as _debate_store
from telegram_bot_new.mock_messenger.stores import messages_store as _messages_store
from telegram_bot_new.mock_messenger.stores import updates_store as _updates_store

MockMessengerStore.set_webhook = _updates_store.set_webhook
MockMessengerStore.delete_webhook = _updates_store.delete_webhook
MockMessengerStore.enqueue_user_message = _updates_store.enqueue_user_message
MockMessengerStore.fetch_updates = _updates_store.fetch_updates
MockMessengerStore.mark_update_delivered = _updates_store.mark_update_delivered
MockMessengerStore.get_recent_updates = _updates_store.get_recent_updates

MockMessengerStore.store_bot_message = _messages_store.store_bot_message
MockMessengerStore.edit_bot_message = _messages_store.edit_bot_message
MockMessengerStore.record_callback_answer = _messages_store.record_callback_answer
MockMessengerStore.store_document = _messages_store.store_document
MockMessengerStore.list_threads = _messages_store.list_threads
MockMessengerStore.clear_messages = _messages_store.clear_messages
MockMessengerStore.get_messages = _messages_store.get_messages
MockMessengerStore.get_document_file = _messages_store.get_document_file
MockMessengerStore.set_rate_limit_rule = _messages_store.set_rate_limit_rule
MockMessengerStore.consume_rate_limit = _messages_store.consume_rate_limit

MockMessengerStore.create_debate = _debate_store.create_debate
MockMessengerStore.set_debate_running = _debate_store.set_debate_running
MockMessengerStore.set_debate_stop_requested = _debate_store.set_debate_stop_requested
MockMessengerStore.get_debate = _debate_store.get_debate
MockMessengerStore.get_active_debate = _debate_store.get_active_debate
MockMessengerStore.insert_debate_turn_start = _debate_store.insert_debate_turn_start
MockMessengerStore.finish_debate_turn = _debate_store.finish_debate_turn
MockMessengerStore.finish_debate = _debate_store.finish_debate
MockMessengerStore.list_debate_turns = _debate_store.list_debate_turns
MockMessengerStore.list_debate_participants = _debate_store.list_debate_participants

MockMessengerStore.create_cowork = _cowork_store.create_cowork
MockMessengerStore.set_cowork_running = _cowork_store.set_cowork_running
MockMessengerStore.set_cowork_stop_requested = _cowork_store.set_cowork_stop_requested
MockMessengerStore.get_cowork = _cowork_store.get_cowork
MockMessengerStore.get_active_cowork = _cowork_store.get_active_cowork
MockMessengerStore.insert_cowork_stage_start = _cowork_store.insert_cowork_stage_start
MockMessengerStore.finish_cowork_stage = _cowork_store.finish_cowork_stage
MockMessengerStore.insert_cowork_task = _cowork_store.insert_cowork_task
MockMessengerStore.start_cowork_task = _cowork_store.start_cowork_task
MockMessengerStore.finish_cowork_task = _cowork_store.finish_cowork_task
MockMessengerStore.finish_cowork = _cowork_store.finish_cowork
MockMessengerStore.list_cowork_participants = _cowork_store.list_cowork_participants
MockMessengerStore.list_cowork_stages = _cowork_store.list_cowork_stages
MockMessengerStore.list_cowork_tasks = _cowork_store.list_cowork_tasks
