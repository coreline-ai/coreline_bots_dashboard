from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from telegram_bot_new.mock_messenger.store import MockMessengerStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_sec() -> int:
    return int(time.time())


def store_bot_message(self: MockMessengerStore, *, token: str, chat_id: int, text: str) -> dict[str, Any]:
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


def edit_bot_message(self: MockMessengerStore, *, token: str, chat_id: int, message_id: int, text: str) -> dict[str, Any] | None:
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


def record_callback_answer(self: MockMessengerStore, *, token: str, callback_query_id: str, text: str | None) -> None:
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
    self: MockMessengerStore,
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


def list_threads(self: MockMessengerStore, *, token: str | None = None) -> list[dict[str, Any]]:
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


def clear_messages(self: MockMessengerStore, *, token: str, chat_id: int | None = None) -> dict[str, int]:
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


def get_messages(self: MockMessengerStore, *, token: str, chat_id: int | None, limit: int) -> list[dict[str, Any]]:
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


def get_document_file(self: MockMessengerStore, *, token: str, document_id: int) -> dict[str, Any] | None:
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


def set_rate_limit_rule(self: MockMessengerStore, *, token: str, method: str, count: int, retry_after: int) -> None:
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


def consume_rate_limit(self: MockMessengerStore, *, token: str, method: str) -> int | None:
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
