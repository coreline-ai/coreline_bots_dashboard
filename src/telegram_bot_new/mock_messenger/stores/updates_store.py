from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from telegram_bot_new.mock_messenger.store import MockMessengerStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_sec() -> int:
    return int(time.time())


def set_webhook(self: MockMessengerStore, *, token: str, url: str, secret_token: str | None, drop_pending_updates: bool) -> None:
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


def delete_webhook(self: MockMessengerStore, *, token: str, drop_pending_updates: bool) -> None:
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


def enqueue_user_message(self: MockMessengerStore, *, token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
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
    self: MockMessengerStore,
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


def mark_update_delivered(self: MockMessengerStore, *, token: str, update_id: int) -> None:
    with self._lock:
        self._conn.execute(
            "UPDATE updates SET delivered = 1 WHERE token = ? AND update_id = ?",
            (token, update_id),
        )
        self._conn.commit()


def get_recent_updates(self: MockMessengerStore, *, token: str, chat_id: int | None, limit: int) -> list[dict[str, Any]]:
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
