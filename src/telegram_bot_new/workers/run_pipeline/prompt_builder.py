from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telegram_bot_new.db.repository import Repository


@dataclass(slots=True)
class PromptExecutionContext:
    session_provider: str
    route: Any
    provider: str
    routed_prompt: str
    adapter: Any
    preamble: str
    run_started_epoch: float
    artifact_output_dir: Path
    execution_prompt: str
    selected_model: str | None
    selected_sandbox: str
    selected_workdir: str | None
    routed_provider_changed: bool


async def build_execution_context(
    *,
    bot_id: str,
    turn: Any,
    session: Any,
    repository: Repository,
    default_models_by_provider: dict[str, str | None],
    default_sandbox: str,
    now_ms_fn,
    get_adapter_fn,
    suggest_route_fn,
    resolve_selected_model_fn,
    build_skill_instruction_fn,
    build_recovery_preamble_fn,
    build_turn_artifact_output_dir_fn,
    augment_prompt_for_generation_request_fn,
    logger: logging.Logger,
) -> PromptExecutionContext:
    session_provider = str(session.adapter_name or "codex")
    route = suggest_route_fn(
        prompt=turn.user_text,
        session_provider=session_provider,
        session_model=getattr(session, "adapter_model", None),
        default_models=default_models_by_provider,
    )
    provider = route.provider
    routed_prompt = route.stripped_prompt.strip() if route.enabled else turn.user_text
    if not routed_prompt:
        routed_prompt = turn.user_text

    adapter = get_adapter_fn(provider)
    preamble = _build_preamble(
        session=session,
        routed_prompt=routed_prompt,
        build_skill_instruction_fn=build_skill_instruction_fn,
        build_recovery_preamble_fn=build_recovery_preamble_fn,
    )

    run_started_epoch = time.time()
    artifact_output_dir = build_turn_artifact_output_dir_fn(
        bot_id=bot_id,
        chat_id=str(turn.chat_id),
        turn_id=turn.turn_id,
    )
    artifact_output_dir.mkdir(parents=True, exist_ok=True)
    execution_prompt = augment_prompt_for_generation_request_fn(
        routed_prompt,
        artifact_output_dir=artifact_output_dir,
    )

    selected_model = route.model or resolve_selected_model_fn(
        provider=provider,
        session_model=(getattr(session, "adapter_model", None) if provider == session_provider else None),
        default_models=default_models_by_provider,
    )

    selected_sandbox = default_sandbox if provider == "codex" else ""
    selected_workdir = getattr(session, "project_root", None)
    session_unsafe_until = getattr(session, "unsafe_until", None)
    if provider == "codex" and isinstance(session_unsafe_until, int):
        now_ms = now_ms_fn()
        if session_unsafe_until > now_ms:
            selected_sandbox = "danger-full-access"
        else:
            try:
                await repository.set_session_unsafe_until(
                    session_id=session.session_id,
                    unsafe_until=None,
                    now=now_ms,
                )
            except Exception:
                logger.exception("failed to clear expired unsafe mode session=%s", session.session_id)

    if selected_workdir:
        project_dir = Path(selected_workdir).expanduser()
        if not project_dir.exists() or not project_dir.is_dir():
            selected_workdir = None

    routed_provider_changed = provider != session_provider
    return PromptExecutionContext(
        session_provider=session_provider,
        route=route,
        provider=provider,
        routed_prompt=routed_prompt,
        adapter=adapter,
        preamble=preamble,
        run_started_epoch=run_started_epoch,
        artifact_output_dir=artifact_output_dir,
        execution_prompt=execution_prompt,
        selected_model=selected_model,
        selected_sandbox=selected_sandbox,
        selected_workdir=selected_workdir,
        routed_provider_changed=routed_provider_changed,
    )


def _build_preamble(*, session: Any, routed_prompt: str, build_skill_instruction_fn, build_recovery_preamble_fn) -> str:
    preamble = build_recovery_preamble_fn(getattr(session, "rolling_summary_md", ""))
    active_skill = getattr(session, "active_skill", None)
    if not active_skill:
        return preamble

    skill_instruction = build_skill_instruction_fn(
        skill_id=active_skill,
        prompt=routed_prompt,
    )
    if not skill_instruction:
        return preamble

    prefix = "[Skill Guidance]\n"
    if preamble and preamble.strip():
        return f"{preamble.strip()}\n\n{prefix}{skill_instruction}"
    return f"{prefix}{skill_instruction}"
