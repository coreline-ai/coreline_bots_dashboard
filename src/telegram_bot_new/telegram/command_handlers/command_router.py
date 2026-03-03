from __future__ import annotations

async def _handle_command(self, *, chat_id: int, text: str, now_ms: int) -> None:
    command, *parts = text.split(maxsplit=1)
    arg = parts[0].strip() if parts else ""

    if command == "/start":
        await self._client.send_message(chat_id, self._welcome_text())
        return

    if command == "/help":
        await self._client.send_message(chat_id, self._help_text())
        return

    if command in ("/youtube", "/yt"):
        if self._youtube_search is None:
            await self._client.send_message(chat_id, "YouTube search is not enabled.")
            return
        if not arg:
            await self._client.send_message(chat_id, "Usage: /youtube <query>")
            return
        await self._handle_youtube_search(chat_id=chat_id, query=arg)
        return

    if command == "/new":
        await self._handle_new_command(chat_id=chat_id, now_ms=now_ms)
        return

    if command == "/status":
        await self._handle_status_command(chat_id=chat_id)
        return

    if command == "/reset":
        await self._handle_reset_command(chat_id=chat_id, now_ms=now_ms)
        return

    if command == "/summary":
        await self._handle_summary_command(chat_id=chat_id)
        return

    if command == "/mode":
        await self._handle_mode_command(chat_id=chat_id, arg=arg, now_ms=now_ms)
        return

    if command == "/model":
        await self._handle_model_command(chat_id=chat_id, arg=arg, now_ms=now_ms)
        return

    if command == "/project":
        await self._handle_project_command(chat_id=chat_id, arg=arg, now_ms=now_ms)
        return

    if command == "/skills":
        await self._handle_skills_command(chat_id=chat_id)
        return

    if command == "/skill":
        await self._handle_skill_command(chat_id=chat_id, arg=arg, now_ms=now_ms)
        return

    if command == "/unsafe":
        await self._handle_unsafe_command(chat_id=chat_id, arg=arg, now_ms=now_ms)
        return

    if command == "/providers":
        await self._handle_providers_command(chat_id=chat_id)
        return

    if command == "/stop":
        await self._handle_stop_command(chat_id=chat_id, now_ms=now_ms)
        return

    if command == "/echo":
        await self._client.send_message(chat_id, arg or "(empty)")
        return

    await self._client.send_message(chat_id, f"Unknown command: {command}\n\n{self._help_text()}")
