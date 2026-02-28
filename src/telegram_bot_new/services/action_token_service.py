from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from telegram_bot_new.db.repository import Repository


DEFAULT_TOKEN_TTL_MS = 24 * 60 * 60 * 1000


@dataclass(slots=True)
class ActionTokenPayload:
    action_type: str
    run_source: str
    chat_id: str
    session_id: str
    origin_turn_id: str


class ActionTokenService:
    def __init__(self, repository: Repository, *, ttl_ms: int = DEFAULT_TOKEN_TTL_MS) -> None:
        self._repository = repository
        self._ttl_ms = max(60_000, ttl_ms)

    async def issue(
        self,
        *,
        bot_id: str,
        chat_id: str,
        action_type: str,
        run_source: str,
        session_id: str,
        origin_turn_id: str,
        now: int,
    ) -> str:
        token = uuid4().hex
        payload = {
            "action_type": action_type,
            "run_source": run_source,
            "chat_id": chat_id,
            "session_id": session_id,
            "origin_turn_id": origin_turn_id,
        }
        await self._repository.create_action_token(
            token=token,
            bot_id=bot_id,
            chat_id=chat_id,
            action=action_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
            expires_at=now + self._ttl_ms,
            now=now,
        )
        return token

    async def consume(
        self,
        *,
        token: str,
        bot_id: str,
        chat_id: str,
        now: int,
    ) -> ActionTokenPayload | None:
        found = await self._repository.consume_action_token(
            token=token,
            bot_id=bot_id,
            chat_id=chat_id,
            now=now,
        )
        if found is None:
            return None
        try:
            payload = json.loads(found.payload_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        action_type = payload.get("action_type")
        run_source = payload.get("run_source")
        payload_chat_id = payload.get("chat_id")
        session_id = payload.get("session_id")
        origin_turn_id = payload.get("origin_turn_id")
        if not all(isinstance(v, str) and v for v in [action_type, run_source, payload_chat_id, session_id, origin_turn_id]):
            return None
        return ActionTokenPayload(
            action_type=action_type,
            run_source=run_source,
            chat_id=payload_chat_id,
            session_id=session_id,
            origin_turn_id=origin_turn_id,
        )
