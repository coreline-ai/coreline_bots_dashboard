from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ParsedIncomingUpdate:
    update_id: int
    chat_id: int
    user_id: int
    message_id: int | None
    text: str | None
    callback_query_id: str | None
    callback_data: str | None
    raw_payload: dict[str, Any]


def extract_chat_id(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if isinstance(message, dict):
        chat = message.get("chat")
        if isinstance(chat, dict) and isinstance(chat.get("id"), (int, str)):
            return str(chat["id"])

    callback_query = payload.get("callback_query")
    if isinstance(callback_query, dict):
        message2 = callback_query.get("message")
        if isinstance(message2, dict):
            chat = message2.get("chat")
            if isinstance(chat, dict) and isinstance(chat.get("id"), (int, str)):
                return str(chat["id"])

    return None


def parse_incoming_update(payload: dict[str, Any]) -> ParsedIncomingUpdate | None:
    update_id = payload.get("update_id")
    if not isinstance(update_id, int):
        return None

    message = payload.get("message")
    if isinstance(message, dict):
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        from_user = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat_id = chat.get("id")
        user_id = from_user.get("id")
        message_id = message.get("message_id")
        text = message.get("text")
        if isinstance(chat_id, int) and isinstance(user_id, int):
            return ParsedIncomingUpdate(
                update_id=update_id,
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id if isinstance(message_id, int) else None,
                text=text if isinstance(text, str) else None,
                callback_query_id=None,
                callback_data=None,
                raw_payload=payload,
            )

    callback_query = payload.get("callback_query")
    if isinstance(callback_query, dict):
        from_user = callback_query.get("from") if isinstance(callback_query.get("from"), dict) else {}
        message2 = callback_query.get("message") if isinstance(callback_query.get("message"), dict) else {}
        chat = message2.get("chat") if isinstance(message2.get("chat"), dict) else {}
        callback_id = callback_query.get("id")
        callback_data = callback_query.get("data")
        chat_id = chat.get("id")
        user_id = from_user.get("id")
        message_id = message2.get("message_id")
        if isinstance(chat_id, int) and isinstance(user_id, int) and isinstance(callback_id, str):
            return ParsedIncomingUpdate(
                update_id=update_id,
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id if isinstance(message_id, int) else None,
                text=None,
                callback_query_id=callback_id,
                callback_data=callback_data if isinstance(callback_data, str) else None,
                raw_payload=payload,
            )

    return None