from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
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
                """
            )
            self._conn.commit()

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

    def _next_update_id_locked(self, *, token: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(update_id), 0) AS max_update_id FROM updates WHERE token = ?",
            (token,),
        ).fetchone()
        return int(row["max_update_id"]) + 1

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
