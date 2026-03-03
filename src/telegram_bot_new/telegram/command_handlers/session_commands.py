from __future__ import annotations

from telegram_bot_new.model_presets import resolve_selected_model


async def _resolve_chat_adapter(self, *, chat_id: str) -> str:
    status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=chat_id)
    if status is not None and status.adapter_name:
        return status.adapter_name
    return self._bot.adapter


async def _handle_new_command(self, *, chat_id: int, now_ms: int) -> None:
    existing = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    adapter_name = existing.adapter_name if existing is not None else await self._resolve_chat_adapter(chat_id=str(chat_id))
    adapter_model = self._provider_default_or_preset_model(adapter_name)
    session = await self._session_service.create_new(
        bot_id=self._bot.bot_id,
        chat_id=str(chat_id),
        adapter_name=adapter_name,
        adapter_model=adapter_model,
        active_skill=getattr(existing, "active_skill", None),
        project_root=getattr(existing, "project_root", None),
        unsafe_until=getattr(existing, "unsafe_until", None),
        now=now_ms,
    )
    await self._append_audit_log(
        chat_id=chat_id,
        session_id=session.session_id,
        action="session.new",
        result="success",
        detail=f"adapter={adapter_name}",
        now_ms=now_ms,
    )
    await self._client.send_message(chat_id, f"New session created: {session.session_id} (adapter={adapter_name})")


async def _handle_status_command(self, *, chat_id: int) -> None:
    status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    if status is None:
        await self._client.send_message(chat_id, "No session yet. Send a message to start.")
        return
    model = resolve_selected_model(
        provider=status.adapter_name,
        session_model=getattr(status, "adapter_model", None),
        default_models=self._bot.default_models,
    )
    await self._client.send_message(
        chat_id,
        "\n".join(
            [
                f"bot={self._bot.bot_id}",
                f"adapter={status.adapter_name}",
                f"model={model or 'default'}",
                f"skill={getattr(status, 'active_skill', None) or 'off'}",
                f"project={getattr(status, 'project_root', None) or 'default'}",
                f"unsafe_until={getattr(status, 'unsafe_until', None) or 'off'}",
                f"session={status.session_id}",
                f"thread={status.adapter_thread_id or 'none'}",
                f"summary={status.summary_preview or 'none'}",
            ]
        ),
    )


async def _handle_reset_command(self, *, chat_id: int, now_ms: int) -> None:
    existing = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    adapter_name = existing.adapter_name if existing is not None else self._bot.adapter
    adapter_model = self._provider_default_or_preset_model(adapter_name)
    if existing:
        await self._session_service.reset(session_id=existing.session_id, now=now_ms)
    new_s = await self._session_service.create_new(
        bot_id=self._bot.bot_id,
        chat_id=str(chat_id),
        adapter_name=adapter_name,
        adapter_model=adapter_model,
        active_skill=getattr(existing, "active_skill", None),
        project_root=getattr(existing, "project_root", None),
        unsafe_until=getattr(existing, "unsafe_until", None),
        now=now_ms,
    )
    await self._append_audit_log(
        chat_id=chat_id,
        session_id=new_s.session_id,
        action="session.reset",
        result="success",
        detail=f"adapter={adapter_name}",
        now_ms=now_ms,
    )
    await self._client.send_message(chat_id, f"Session reset. New session={new_s.session_id} (adapter={adapter_name})")


async def _handle_summary_command(self, *, chat_id: int) -> None:
    summary = await self._session_service.get_summary(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    if not summary.strip():
        await self._client.send_message(chat_id, "No summary yet.")
    else:
        await self._client.send_message(chat_id, f"Summary:\n{summary[:3500]}")


async def _handle_stop_command(self, *, chat_id: int, now_ms: int) -> None:
    stopped = await self._run_service.stop_active_turn(bot_id=self._bot.bot_id, chat_id=str(chat_id), now=now_ms)
    await self._append_audit_log(
        chat_id=chat_id,
        session_id=None,
        action="run.stop",
        result="success" if stopped else "noop",
        detail=None,
        now_ms=now_ms,
    )
    await self._client.send_message(chat_id, "Stop requested." if stopped else "No active run.")

