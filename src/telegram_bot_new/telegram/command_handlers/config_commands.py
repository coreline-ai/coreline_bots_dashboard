from __future__ import annotations

from pathlib import Path

from telegram_bot_new.model_presets import (
    SUPPORTED_CLI_PROVIDERS,
    get_available_models,
    is_allowed_model,
    resolve_provider_default_model,
    resolve_selected_model,
)
from telegram_bot_new.provider_binaries import is_provider_installed
from telegram_bot_new.skill_library import list_installed_skills, resolve_skill_ids

SUPPORTED_PROVIDERS = SUPPORTED_CLI_PROVIDERS


def _provider_default_model(self, provider: str) -> str | None:
    return self._bot.default_models.get(provider)


def _provider_default_or_preset_model(self, provider: str) -> str | None:
    return resolve_provider_default_model(provider, self._provider_default_model(provider))


def _provider_models_text(self, provider: str) -> str:
    candidates = get_available_models(provider)
    if not candidates:
        return "none"
    return ", ".join(candidates)


async def _handle_mode_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
    status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    current_adapter = status.adapter_name if status is not None else self._bot.adapter
    current_model = resolve_selected_model(
        provider=current_adapter,
        session_model=getattr(status, "adapter_model", None),
        default_models=self._bot.default_models,
    ) or "default"

    if not arg:
        await self._client.send_message(
            chat_id,
            "\n".join(
                [
                    f"mode=cli adapter={current_adapter} model={current_model}",
                    "usage: /mode <codex|gemini|claude>",
                    f"providers={', '.join(SUPPORTED_PROVIDERS)}",
                ]
            ),
        )
        return

    next_adapter = arg.lower().strip()
    if next_adapter not in SUPPORTED_PROVIDERS:
        await self._client.send_message(
            chat_id,
            f"Unsupported provider: {arg}. Use one of: {', '.join(SUPPORTED_PROVIDERS)}",
        )
        return

    if next_adapter == current_adapter:
        await self._client.send_message(chat_id, f"mode unchanged: adapter={current_adapter}")
        return

    active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    if active:
        await self._client.send_message(chat_id, "A run is active. Use /stop first, then retry /mode.")
        return

    if status is None:
        session = await self._session_service.get_or_create(
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            adapter_name=next_adapter,
            adapter_model=self._provider_default_or_preset_model(next_adapter),
            now=now_ms,
        )
        await self._session_service.switch_adapter(
            session_id=session.session_id,
            adapter_name=next_adapter,
            adapter_model=self._provider_default_or_preset_model(next_adapter),
            now=now_ms,
        )
        session_id = session.session_id
    else:
        await self._session_service.switch_adapter(
            session_id=status.session_id,
            adapter_name=next_adapter,
            adapter_model=self._provider_default_or_preset_model(next_adapter),
            now=now_ms,
        )
        session_id = status.session_id

    await self._increment_metric(f"provider_switch_total.{next_adapter}", now_ms=now_ms)
    await self._append_audit_log(
        chat_id=chat_id,
        session_id=session_id,
        action="session.switch_adapter",
        result="success",
        detail=f"{current_adapter}->{next_adapter}",
        now_ms=now_ms,
    )
    await self._client.send_message(
        chat_id,
        "\n".join(
            [
                f"mode switched: {current_adapter} -> {next_adapter}",
                f"model={self._provider_default_or_preset_model(next_adapter) or 'default'}",
                f"session={session_id}",
                "context continuity: rolling summary retained, provider thread reset.",
            ]
        ),
    )


async def _handle_model_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
    status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    current_adapter = status.adapter_name if status is not None else self._bot.adapter
    current_model = resolve_selected_model(
        provider=current_adapter,
        session_model=getattr(status, "adapter_model", None),
        default_models=self._bot.default_models,
    ) or "default"
    allowed_models = get_available_models(current_adapter)

    if not arg:
        await self._client.send_message(
            chat_id,
            "\n".join(
                [
                    f"adapter={current_adapter}",
                    f"model={current_model}",
                    f"available_models={self._provider_models_text(current_adapter)}",
                    "usage: /model <model-name>",
                ]
            ),
        )
        return

    next_model = arg.strip()
    if not next_model:
        await self._client.send_message(chat_id, "Model name is required. usage: /model <model-name>")
        return

    if not allowed_models:
        await self._client.send_message(chat_id, f"No selectable model for provider={current_adapter}")
        return

    if not is_allowed_model(current_adapter, next_model):
        await self._client.send_message(
            chat_id,
            f"Unsupported model for {current_adapter}: {next_model}\nallowed={self._provider_models_text(current_adapter)}",
        )
        return

    active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    if active:
        await self._client.send_message(chat_id, "A run is active. Use /stop first, then retry /model.")
        return

    if status is None:
        session = await self._session_service.get_or_create(
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            adapter_name=current_adapter,
            adapter_model=next_model,
            now=now_ms,
        )
        session_id = session.session_id
    else:
        session_id = status.session_id

    await self._session_service.set_model(
        session_id=session_id,
        adapter_model=next_model,
        now=now_ms,
    )
    await self._append_audit_log(
        chat_id=chat_id,
        session_id=session_id,
        action="session.set_model",
        result="success",
        detail=f"{current_model}->{next_model}",
        now_ms=now_ms,
    )
    await self._client.send_message(
        chat_id,
        "\n".join(
            [
                f"model updated: {current_model} -> {next_model}",
                f"adapter={current_adapter}",
                f"model={next_model}",
                f"session={session_id}",
            ]
        ),
    )


async def _handle_providers_command(self, *, chat_id: int) -> None:
    lines = ["Available CLI providers:"]
    for provider in SUPPORTED_PROVIDERS:
        installed = "yes" if is_provider_installed(provider) else "no"
        model = self._provider_default_model(provider) or "default"
        lines.append(f"- {provider}: installed={installed}, model={model}")
    await self._client.send_message(chat_id, "\n".join(lines))


async def _handle_project_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
    status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    current_project = getattr(status, "project_root", None)

    if not arg:
        await self._client.send_message(
            chat_id,
            "\n".join(
                [
                    f"project={current_project or 'default'}",
                    "usage: /project <directory-path>",
                    "reset: /project off",
                ]
            ),
        )
        return

    arg_value = arg.strip()
    disable_aliases = {"off", "none", "default", "reset"}
    next_project: str | None
    if arg_value.lower() in disable_aliases:
        next_project = None
    else:
        candidate = Path(arg_value).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()

        if not candidate.exists():
            await self._client.send_message(chat_id, f"Directory not found: {candidate}")
            return
        if not candidate.is_dir():
            await self._client.send_message(chat_id, f"Not a directory: {candidate}")
            return
        next_project = str(candidate)

    active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    if active:
        await self._client.send_message(chat_id, "A run is active. Use /stop first, then retry /project.")
        return

    adapter_name = status.adapter_name if status is not None else self._bot.adapter
    adapter_model = resolve_selected_model(
        provider=adapter_name,
        session_model=getattr(status, "adapter_model", None),
        default_models=self._bot.default_models,
    )
    if status is None:
        session = await self._session_service.get_or_create(
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            active_skill=getattr(status, "active_skill", None),
            project_root=next_project,
            now=now_ms,
        )
        session_id = session.session_id
    else:
        session_id = status.session_id
        await self._session_service.set_project_root(
            session_id=session_id,
            project_root=next_project,
            now=now_ms,
        )

    await self._client.send_message(
        chat_id,
        "\n".join(
            [
                f"project updated: {current_project or 'default'} -> {next_project or 'default'}",
                f"session={session_id}",
            ]
        ),
    )
    await self._append_audit_log(
        chat_id=chat_id,
        session_id=session_id,
        action="session.set_project",
        result="success",
        detail=f"{current_project or 'default'}->{next_project or 'default'}",
        now_ms=now_ms,
    )


async def _handle_skills_command(self, *, chat_id: int) -> None:
    installed = list_installed_skills()
    if not installed:
        await self._client.send_message(chat_id, "No local skills found. Put skills under ./skills/<name>/SKILL.md")
        return
    lines = ["Installed skills:"]
    for skill in installed:
        summary = skill.description or "no description"
        lines.append(f"- {skill.skill_id}: {summary}")
    await self._client.send_message(chat_id, "\n".join(lines))


async def _handle_skill_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
    status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    current_skill = getattr(status, "active_skill", None)

    if not arg:
        await self._client.send_message(
            chat_id,
            "\n".join(
                [
                    f"skill={current_skill or 'off'}",
                    "usage: /skill <skill-id[,skill-id...]>",
                    "disable: /skill off",
                    "list: /skills",
                ]
            ),
        )
        return

    next_raw = arg.strip()
    disable_aliases = {"off", "none", "default", "reset"}
    if next_raw.lower() in disable_aliases:
        next_skill = None
    else:
        resolved_ids, unknown_ids = resolve_skill_ids(name_or_ids=next_raw)
        if unknown_ids or not resolved_ids:
            available = ", ".join(skill.skill_id for skill in list_installed_skills()) or "none"
            unknown_text = ", ".join(unknown_ids) if unknown_ids else next_raw
            await self._client.send_message(chat_id, f"Unknown skill: {unknown_text}\navailable={available}")
            return
        next_skill = ",".join(resolved_ids)

    active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    if active:
        await self._client.send_message(chat_id, "A run is active. Use /stop first, then retry /skill.")
        return

    adapter_name = status.adapter_name if status is not None else self._bot.adapter
    adapter_model = resolve_selected_model(
        provider=adapter_name,
        session_model=getattr(status, "adapter_model", None),
        default_models=self._bot.default_models,
    )
    if status is None:
        session = await self._session_service.get_or_create(
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            active_skill=next_skill,
            project_root=getattr(status, "project_root", None),
            unsafe_until=getattr(status, "unsafe_until", None),
            now=now_ms,
        )
        session_id = session.session_id
    else:
        session_id = status.session_id
        await self._session_service.set_skill(
            session_id=session_id,
            active_skill=next_skill,
            now=now_ms,
        )

    await self._client.send_message(
        chat_id,
        "\n".join(
            [
                f"skill updated: {current_skill or 'off'} -> {next_skill or 'off'}",
                f"session={session_id}",
            ]
        ),
    )
    await self._append_audit_log(
        chat_id=chat_id,
        session_id=session_id,
        action="session.set_skill",
        result="success",
        detail=f"{current_skill or 'off'}->{next_skill or 'off'}",
        now_ms=now_ms,
    )


async def _handle_unsafe_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
    status = await self._session_service.status(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    current_unsafe_until = getattr(status, "unsafe_until", None)

    if not arg:
        await self._client.send_message(
            chat_id,
            "\n".join(
                [
                    f"unsafe_until={current_unsafe_until or 'off'}",
                    "usage: /unsafe on [minutes]",
                    "usage: /unsafe off",
                ]
            ),
        )
        return

    parts = [piece for piece in arg.split() if piece.strip()]
    head = parts[0].lower()

    next_unsafe_until: int | None
    if head in {"off", "0", "disable"}:
        next_unsafe_until = None
    else:
        minutes = 10
        if head in {"on", "1", "enable"}:
            if len(parts) >= 2:
                try:
                    minutes = int(parts[1])
                except ValueError:
                    await self._client.send_message(chat_id, "Invalid minutes. usage: /unsafe on [1-120]")
                    return
        else:
            try:
                minutes = int(parts[0])
            except ValueError:
                await self._client.send_message(chat_id, "Invalid argument. usage: /unsafe on [minutes] | /unsafe off")
                return

        if minutes < 1 or minutes > 120:
            await self._client.send_message(chat_id, "Minutes out of range. allowed=1..120")
            return
        next_unsafe_until = now_ms + (minutes * 60 * 1000)

    active = await self._run_service.has_active_run(bot_id=self._bot.bot_id, chat_id=str(chat_id))
    if active:
        await self._client.send_message(chat_id, "A run is active. Use /stop first, then retry /unsafe.")
        return

    adapter_name = status.adapter_name if status is not None else self._bot.adapter
    adapter_model = resolve_selected_model(
        provider=adapter_name,
        session_model=getattr(status, "adapter_model", None),
        default_models=self._bot.default_models,
    )
    if status is None:
        session = await self._session_service.get_or_create(
            bot_id=self._bot.bot_id,
            chat_id=str(chat_id),
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            active_skill=getattr(status, "active_skill", None),
            project_root=getattr(status, "project_root", None),
            unsafe_until=next_unsafe_until,
            now=now_ms,
        )
        session_id = session.session_id
    else:
        session_id = status.session_id
        await self._session_service.set_unsafe_until(
            session_id=session_id,
            unsafe_until=next_unsafe_until,
            now=now_ms,
        )

    await self._client.send_message(
        chat_id,
        "\n".join(
            [
                f"unsafe updated: {current_unsafe_until or 'off'} -> {next_unsafe_until or 'off'}",
                f"session={session_id}",
            ]
        ),
    )
    await self._append_audit_log(
        chat_id=chat_id,
        session_id=session_id,
        action="session.set_unsafe",
        result="success",
        detail=f"{current_unsafe_until or 'off'}->{next_unsafe_until or 'off'}",
        now_ms=now_ms,
    )
