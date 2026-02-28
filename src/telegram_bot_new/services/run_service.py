from __future__ import annotations

from telegram_bot_new.db.repository import Repository


class RunService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def enqueue_turn(
        self,
        *,
        session_id: str,
        bot_id: str,
        chat_id: str,
        user_text: str,
        now: int,
    ) -> str:
        return await self._repository.create_turn_and_job(
            session_id=session_id,
            bot_id=bot_id,
            chat_id=chat_id,
            user_text=user_text,
            available_at=now,
        )

    async def stop_active_turn(self, *, bot_id: str, chat_id: str, now: int) -> str | None:
        return await self._repository.cancel_active_turn(bot_id=bot_id, chat_id=chat_id, now=now)

    async def has_active_run(self, *, bot_id: str, chat_id: str) -> bool:
        return await self._repository.has_active_run(bot_id=bot_id, chat_id=chat_id)

    async def enqueue_button_turn(
        self,
        *,
        session_id: str,
        bot_id: str,
        chat_id: str,
        prompt_text: str,
        now: int,
    ) -> str:
        return await self.enqueue_turn(
            session_id=session_id,
            bot_id=bot_id,
            chat_id=chat_id,
            user_text=prompt_text,
            now=now,
        )

    async def enqueue_deferred_button_action(
        self,
        *,
        bot_id: str,
        chat_id: str,
        session_id: str,
        action_type: str,
        prompt_text: str,
        origin_turn_id: str,
        now: int,
        max_queue: int = 10,
    ) -> str:
        return await self._repository.enqueue_deferred_button_action(
            bot_id=bot_id,
            chat_id=chat_id,
            session_id=session_id,
            action_type=action_type,
            prompt_text=prompt_text,
            origin_turn_id=origin_turn_id,
            max_queue=max_queue,
            now=now,
        )

    async def promote_next_deferred_action(self, *, bot_id: str, chat_id: str, now: int) -> str | None:
        promoted = await self._repository.promote_next_deferred_action(
            bot_id=bot_id,
            chat_id=chat_id,
            now=now,
        )
        if promoted is None:
            return None
        return promoted.turn_id
