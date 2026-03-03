from __future__ import annotations

import logging
import time

from telegram_bot_new.db.repository import ActiveRunExistsError
from telegram_bot_new.services.action_token_service import ActionTokenPayload

LOGGER = logging.getLogger(__name__)


async def _handle_callback(self, chat_id: int, callback_query_id: str, callback_data: str, now_ms: int) -> None:
    if callback_data == "stop_run":
        stopped = await self._run_service.stop_active_turn(bot_id=self._bot.bot_id, chat_id=str(chat_id), now=now_ms)
        await self._answer_callback(callback_query_id, "Stopping..." if stopped else "No active run", now_ms=now_ms)
        return

    if not callback_data.startswith("act:") or self._action_token_service is None:
        await self._answer_callback(callback_query_id, "Unsupported action", now_ms=now_ms)
        return

    token = callback_data.split(":", 1)[1].strip()
    if not token:
        await self._answer_callback(callback_query_id, "Invalid action token", now_ms=now_ms)
        return

    payload = await self._action_token_service.consume(
        token=token,
        bot_id=self._bot.bot_id,
        chat_id=str(chat_id),
        now=now_ms,
    )
    if payload is None:
        await self._answer_callback(callback_query_id, "Action expired or already used", now_ms=now_ms)
        return

    if payload.run_source == "direct_cancel" or payload.action_type == "stop":
        stopped = await self._run_service.stop_active_turn(bot_id=self._bot.bot_id, chat_id=str(chat_id), now=now_ms)
        await self._answer_callback(callback_query_id, "Stopping..." if stopped else "No active run", now_ms=now_ms)
        return

    if payload.action_type not in ("summary", "regen", "next"):
        await self._answer_callback(callback_query_id, "Unknown action", now_ms=now_ms)
        return

    prompt_text = await self._build_prompt_from_action(payload=payload)
    if not prompt_text:
        await self._answer_callback(callback_query_id, "Cannot build prompt for action", now_ms=now_ms)
        return

    active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    if active:
        await self._run_service.enqueue_deferred_button_action(
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            session_id=payload.session_id,
            action_type=payload.action_type,
            prompt_text=prompt_text,
            origin_turn_id=payload.origin_turn_id,
            now=now_ms,
            max_queue=10,
        )
        await self._answer_callback(callback_query_id, "Queued after current run", now_ms=now_ms)
        await self._client.send_message(chat_id, f"[button] queued {payload.action_type} action.")
        return

    try:
        turn_id = await self._run_service.enqueue_button_turn(
            session_id=payload.session_id,
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            prompt_text=prompt_text,
            now=now_ms,
        )
    except ActiveRunExistsError:
        await self._run_service.enqueue_deferred_button_action(
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            session_id=payload.session_id,
            action_type=payload.action_type,
            prompt_text=prompt_text,
            origin_turn_id=payload.origin_turn_id,
            now=now_ms,
            max_queue=10,
        )
        await self._answer_callback(callback_query_id, "Queued after current run", now_ms=now_ms)
        await self._client.send_message(chat_id, f"[button] queued {payload.action_type} action.")
        return

    await self._answer_callback(callback_query_id, "Started", now_ms=now_ms)
    await self._client.send_message(
        chat_id,
        f"[button] queued {payload.action_type}: {turn_id}",
        reply_markup=await self._build_turn_action_keyboard(
            chat_id=chat_id,
            session_id=payload.session_id,
            origin_turn_id=turn_id,
            now_ms=now_ms,
        ),
    )


async def _answer_callback(self, callback_query_id: str, text: str | None = None, *, now_ms: int | None = None) -> None:
    await self._client.answer_callback_query(callback_query_id, text)
    await self._increment_metric("callback_ack_success", now_ms=now_ms)


async def _safe_answer_callback(
    self,
    callback_query_id: str,
    text: str | None = None,
    *,
    now_ms: int | None = None,
) -> None:
    try:
        await self._answer_callback(callback_query_id, text, now_ms=now_ms)
    except Exception:
        await self._increment_metric("callback_ack_failed", now_ms=now_ms)
        LOGGER.exception("failed to answer callback query bot=%s callback_query_id=%s", self._bot.bot_id, callback_query_id)


async def _build_prompt_from_action(self, *, payload: ActionTokenPayload) -> str | None:
    if self._repository is None or self._button_prompt_service is None:
        return None
    session = await self._repository.get_session_view(session_id=payload.session_id)
    if session is None:
        return None
    origin_turn = await self._repository.get_turn(turn_id=payload.origin_turn_id)
    if origin_turn is None:
        return None
    latest = await self._repository.get_latest_completed_turn_for_session(session_id=payload.session_id)
    if payload.action_type == "summary":
        return self._button_prompt_service.build_summary_prompt(
            session=session,
            origin_turn=origin_turn,
            latest_turn=latest,
        )
    if payload.action_type == "regen":
        return self._button_prompt_service.build_regen_prompt(
            session=session,
            origin_turn=origin_turn,
        )
    if payload.action_type == "next":
        latest_assistant = (latest.assistant_text or "") if latest is not None else ""
        return self._button_prompt_service.build_next_prompt(
            session=session,
            origin_turn=origin_turn,
            latest_assistant_text=latest_assistant,
        )
    return None

