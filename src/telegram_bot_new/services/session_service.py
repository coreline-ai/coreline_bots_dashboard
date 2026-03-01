from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from telegram_bot_new.db.repository import Repository, SessionView


@dataclass
class SessionStatus:
    session_id: str
    adapter_name: str
    adapter_model: Optional[str]
    project_root: Optional[str]
    unsafe_until: Optional[int]
    adapter_thread_id: Optional[str]
    summary_preview: str


class SessionService:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def get_or_create(
        self,
        *,
        bot_id: str,
        chat_id: str,
        adapter_name: str,
        adapter_model: Optional[str],
        project_root: Optional[str] = None,
        unsafe_until: Optional[int] = None,
        now: int,
    ) -> SessionView:
        return await self._repository.get_or_create_active_session(
            bot_id=bot_id,
            chat_id=chat_id,
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            project_root=project_root,
            unsafe_until=unsafe_until,
            now=now,
        )

    async def create_new(
        self,
        *,
        bot_id: str,
        chat_id: str,
        adapter_name: str,
        adapter_model: Optional[str],
        project_root: Optional[str] = None,
        unsafe_until: Optional[int] = None,
        now: int,
    ) -> SessionView:
        return await self._repository.create_fresh_session(
            bot_id=bot_id,
            chat_id=chat_id,
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            project_root=project_root,
            unsafe_until=unsafe_until,
            now=now,
        )

    async def reset(self, *, session_id: str, now: int) -> None:
        await self._repository.reset_session(session_id=session_id, now=now)

    async def switch_adapter(
        self,
        *,
        session_id: str,
        adapter_name: str,
        adapter_model: Optional[str],
        now: int,
    ) -> None:
        await self._repository.set_session_adapter(
            session_id=session_id,
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            now=now,
        )

    async def set_model(self, *, session_id: str, adapter_model: Optional[str], now: int) -> None:
        await self._repository.set_session_model(
            session_id=session_id,
            adapter_model=adapter_model,
            now=now,
        )

    async def set_project_root(self, *, session_id: str, project_root: Optional[str], now: int) -> None:
        await self._repository.set_session_project_root(
            session_id=session_id,
            project_root=project_root,
            now=now,
        )

    async def set_unsafe_until(self, *, session_id: str, unsafe_until: Optional[int], now: int) -> None:
        await self._repository.set_session_unsafe_until(
            session_id=session_id,
            unsafe_until=unsafe_until,
            now=now,
        )

    async def status(self, *, bot_id: str, chat_id: str) -> Optional[SessionStatus]:
        session = await self._repository.get_active_session(bot_id=bot_id, chat_id=chat_id)
        if session is None:
            session = await self._repository.get_latest_session(bot_id=bot_id, chat_id=chat_id)
        if session is None:
            return None
        preview = (session.rolling_summary_md or "").strip().replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        return SessionStatus(
            session_id=session.session_id,
            adapter_name=session.adapter_name,
            adapter_model=session.adapter_model,
            project_root=session.project_root,
            unsafe_until=session.unsafe_until,
            adapter_thread_id=session.adapter_thread_id,
            summary_preview=preview,
        )

    async def get_summary(self, *, bot_id: str, chat_id: str) -> str:
        session = await self._repository.get_active_session(bot_id=bot_id, chat_id=chat_id)
        if session is None:
            session = await self._repository.get_latest_session(bot_id=bot_id, chat_id=chat_id)
        if session is None:
            return ""
        return session.rolling_summary_md or ""
