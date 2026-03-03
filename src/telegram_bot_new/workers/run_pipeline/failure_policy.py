from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FailurePolicyResult:
    error_text: str | None
    auto_recovered: bool
    watchdog_timeout: bool


def apply_timeout_status(
    *,
    timed_out: bool,
    completion_status: str,
    error_text: str | None,
    run_turn_timeout_sec: int,
) -> tuple[str, str | None]:
    if not timed_out:
        return completion_status, error_text
    if error_text:
        return "error", error_text
    return "error", f"turn timed out after {run_turn_timeout_sec}s"


async def apply_failure_policy(
    *,
    failed: bool,
    provider: str,
    selected_model: str | None,
    session: Any,
    turn: Any,
    bot_id: str,
    repository: Any,
    now_ms_fn,
    append_audit_log_fn,
    looks_like_watchdog_timeout_error_fn,
    looks_like_gemini_quota_error_fn,
    looks_like_codex_access_limited_error_fn,
    timed_out: bool,
    routed_provider_changed: bool,
    error_text: str | None,
    error_stderr: str | None,
    logger: logging.Logger,
) -> FailurePolicyResult:
    watchdog_timeout = bool(timed_out or looks_like_watchdog_timeout_error_fn(error_text))
    auto_recovered = False

    if failed and watchdog_timeout and session.adapter_thread_id and not routed_provider_changed:
        try:
            await repository.set_session_thread_id(
                session_id=session.session_id,
                thread_id=None,
                now=now_ms_fn(),
            )
            auto_recovered = True
            await append_audit_log_fn(
                repository=repository,
                bot_id=bot_id,
                chat_id=str(turn.chat_id),
                session_id=turn.session_id,
                action="run.auto_recover",
                result="success",
                detail=f"reason=watchdog_timeout thread_reset=true provider={provider}",
                now=now_ms_fn(),
            )
        except Exception:
            logger.exception(
                "failed to auto-recover timed out thread bot=%s session=%s",
                bot_id,
                session.session_id,
            )

    if failed and watchdog_timeout and hasattr(repository, "increment_runtime_metric"):
        try:
            await repository.increment_runtime_metric(
                bot_id=bot_id,
                metric_key=f"provider_run_watchdog_timeout.{provider}",
                now=now_ms_fn(),
            )
        except Exception:
            logger.exception("failed to increment watchdog metric bot=%s provider=%s", bot_id, provider)

    next_error_text = error_text
    if failed and provider == "gemini" and looks_like_gemini_quota_error_fn(error_text, error_stderr):
        fallback_model = "gemini-2.5-flash"
        if selected_model != fallback_model:
            try:
                await repository.set_session_model(
                    session_id=session.session_id,
                    adapter_model=fallback_model,
                    now=now_ms_fn(),
                )
                await append_audit_log_fn(
                    repository=repository,
                    bot_id=bot_id,
                    chat_id=str(turn.chat_id),
                    session_id=turn.session_id,
                    action="session.auto_fallback_model",
                    result="success",
                    detail=f"{selected_model or 'default'}->{fallback_model}",
                    now=now_ms_fn(),
                )
                next_error_text = (
                    f"{(error_text or 'gemini quota exceeded').strip()} "
                    f"(auto-switched model to {fallback_model}; retry the request)"
                )
            except Exception:
                logger.exception(
                    "failed to auto-switch gemini model after quota failure bot=%s session=%s",
                    bot_id,
                    session.session_id,
                )

    if failed and provider == "codex" and looks_like_codex_access_limited_error_fn(error_text, error_stderr):
        fallback_model = "gpt-5"
        if selected_model != fallback_model:
            try:
                await repository.set_session_model(
                    session_id=session.session_id,
                    adapter_model=fallback_model,
                    now=now_ms_fn(),
                )
                await append_audit_log_fn(
                    repository=repository,
                    bot_id=bot_id,
                    chat_id=str(turn.chat_id),
                    session_id=turn.session_id,
                    action="session.auto_fallback_model",
                    result="success",
                    detail=f"{selected_model or 'default'}->{fallback_model}",
                    now=now_ms_fn(),
                )
                next_error_text = (
                    f"{(error_text or 'codex access temporarily limited').strip()} "
                    f"(auto-switched model to {fallback_model}; retry the request)"
                )
            except Exception:
                logger.exception(
                    "failed to auto-switch codex model after access limitation bot=%s session=%s",
                    bot_id,
                    session.session_id,
                )

    return FailurePolicyResult(
        error_text=next_error_text,
        auto_recovered=auto_recovered,
        watchdog_timeout=watchdog_timeout,
    )
