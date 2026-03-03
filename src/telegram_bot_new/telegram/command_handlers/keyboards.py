from __future__ import annotations

from typing import Any

INLINE_ACTIONS = ("summary", "regen", "next", "stop")


async def _build_turn_action_keyboard(
    self,
    *,
    chat_id: int,
    session_id: str,
    origin_turn_id: str,
    now_ms: int,
) -> dict[str, Any] | None:
    if self._action_token_service is None:
        return None
    token_map: dict[str, str] = {}
    for action in INLINE_ACTIONS:
        run_source = "direct_cancel" if action == "stop" else "codex_cli"
        token = await self._action_token_service.issue(
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            action_type=action,
            run_source=run_source,
            session_id=session_id,
            origin_turn_id=origin_turn_id,
            now=now_ms,
        )
        token_map[action] = token

    return {
        "inline_keyboard": [
            [
                {"text": "요약", "callback_data": f"act:{token_map['summary']}"},
                {"text": "다시생성", "callback_data": f"act:{token_map['regen']}"},
            ],
            [
                {"text": "다음추천", "callback_data": f"act:{token_map['next']}"},
                {"text": "중단", "callback_data": f"act:{token_map['stop']}"},
            ],
        ]
    }

