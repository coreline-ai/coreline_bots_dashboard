from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from telegram_bot_new.adapters.base import AdapterResumeRequest, AdapterRunRequest, utc_now_iso
from telegram_bot_new.db.repository import LeasedRunJob, Repository
from telegram_bot_new.services.summary_service import SummaryInput, SummaryService
from telegram_bot_new.streaming.telegram_event_streamer import TelegramEventStreamer
from telegram_bot_new.telegram.client import TelegramClient
from telegram_bot_new.workers.run_pipeline.event_persistence import consume_adapter_stream
from telegram_bot_new.workers.run_pipeline.failure_policy import apply_failure_policy, apply_timeout_status
from telegram_bot_new.workers.run_pipeline.prompt_builder import build_execution_context


AppendAuditLogFn = Callable[..., Awaitable[None]]
DeliverGeneratedArtifactsFn = Callable[..., Awaitable[None]]
RenewLeaseLoopFn = Callable[..., Awaitable[None]]


async def process_run_job(
    *,
    job: LeasedRunJob,
    bot_id: str,
    repository: Repository,
    telegram_client: TelegramClient,
    streamer: TelegramEventStreamer,
    summary_service: SummaryService,
    default_models_by_provider: dict[str, str | None],
    default_sandbox: str,
    lease_ms: int,
    sent_artifacts_by_chat: dict[str, set[str]],
    renew_lease_loop: RenewLeaseLoopFn,
    now_ms_fn: Callable[[], int],
    get_adapter_fn: Callable[[str], Any],
    suggest_route_fn: Callable[..., Any],
    resolve_selected_model_fn: Callable[..., str | None],
    build_skill_instruction_fn: Callable[..., str | None],
    append_audit_log_fn: AppendAuditLogFn,
    build_turn_artifact_output_dir_fn: Callable[..., Path],
    augment_prompt_for_generation_request_fn: Callable[..., str],
    looks_like_watchdog_timeout_error_fn: Callable[[str | None], bool],
    looks_like_gemini_quota_error_fn: Callable[[str | None, str | None], bool],
    looks_like_gemini_human_input_required_error_fn: Callable[[str | None, str | None], bool],
    looks_like_codex_access_limited_error_fn: Callable[[str | None, str | None], bool],
    looks_like_image_request_fn: Callable[[str], bool],
    looks_like_html_request_fn: Callable[[str], bool],
    deliver_generated_artifacts_fn: DeliverGeneratedArtifactsFn,
    run_turn_timeout_sec: int,
    logger: logging.Logger,
    utc_now_iso_fn: Callable[[], str] = utc_now_iso,
) -> None:
    lease_stop = asyncio.Event()
    lease_task = asyncio.create_task(
        renew_lease_loop(job_id=job.id, repository=repository, lease_ms=lease_ms, stop_event=lease_stop)
    )

    try:
        turn = await repository.get_turn(turn_id=job.turn_id)
        if turn is None:
            await repository.fail_run_job_and_turn(job_id=job.id, turn_id=job.turn_id, error_text="missing turn", now=now_ms_fn())
            return

        session = await repository.get_session_view(session_id=turn.session_id)
        if session is None:
            await repository.fail_run_job_and_turn(
                job_id=job.id,
                turn_id=job.turn_id,
                error_text="missing session",
                now=now_ms_fn(),
            )
            return

        await repository.mark_run_in_flight(job_id=job.id, turn_id=turn.turn_id, now=now_ms_fn())

        context = await build_execution_context(
            bot_id=bot_id,
            turn=turn,
            session=session,
            repository=repository,
            default_models_by_provider=default_models_by_provider,
            default_sandbox=default_sandbox,
            now_ms_fn=now_ms_fn,
            get_adapter_fn=get_adapter_fn,
            suggest_route_fn=suggest_route_fn,
            resolve_selected_model_fn=resolve_selected_model_fn,
            build_skill_instruction_fn=build_skill_instruction_fn,
            build_recovery_preamble_fn=summary_service.build_recovery_preamble,
            build_turn_artifact_output_dir_fn=build_turn_artifact_output_dir_fn,
            augment_prompt_for_generation_request_fn=augment_prompt_for_generation_request_fn,
            logger=logger,
        )

        deadline = time.monotonic() + run_turn_timeout_sec
        timed_out = False

        async def should_cancel() -> bool:
            nonlocal timed_out
            if await repository.is_turn_cancelled(turn_id=turn.turn_id):
                return True
            if time.monotonic() >= deadline:
                timed_out = True
                return True
            return False

        if context.route.enabled and (
            context.routed_provider_changed or context.selected_model != getattr(session, "adapter_model", None)
        ):
            await append_audit_log_fn(
                repository=repository,
                bot_id=bot_id,
                chat_id=str(turn.chat_id),
                session_id=turn.session_id,
                action="run.routing",
                result="applied",
                detail=(
                    f"provider={context.session_provider}->{context.provider} "
                    f"model={context.selected_model or 'default'} reason={context.route.reason}"
                ),
                now=now_ms_fn(),
            )

        if session.adapter_thread_id and not context.routed_provider_changed:
            stream = context.adapter.run_resume_turn(
                AdapterResumeRequest(
                    thread_id=session.adapter_thread_id,
                    prompt=context.execution_prompt,
                    model=context.selected_model,
                    sandbox=context.selected_sandbox,
                    workdir=context.selected_workdir,
                    preamble=context.preamble,
                    should_cancel=should_cancel,
                )
            )
        else:
            stream = context.adapter.run_new_turn(
                AdapterRunRequest(
                    prompt=context.execution_prompt,
                    model=context.selected_model,
                    sandbox=context.selected_sandbox,
                    workdir=context.selected_workdir,
                    preamble=context.preamble,
                    should_cancel=should_cancel,
                )
            )

        stream_outcome = await consume_adapter_stream(
            stream=stream,
            adapter=context.adapter,
            provider=context.provider,
            turn=turn,
            bot_id=bot_id,
            repository=repository,
            streamer=streamer,
            now_ms_fn=now_ms_fn,
            utc_now_iso_fn=utc_now_iso_fn,
        )
        assistant_parts = stream_outcome.assistant_parts
        command_notes = stream_outcome.command_notes
        thread_id = stream_outcome.thread_id
        completion_status = stream_outcome.completion_status
        error_text = stream_outcome.error_text
        error_stderr = stream_outcome.error_stderr

        completion_status, error_text = apply_timeout_status(
            timed_out=timed_out,
            completion_status=completion_status,
            error_text=error_text,
            run_turn_timeout_sec=run_turn_timeout_sec,
        )

        cancelled = await repository.is_turn_cancelled(turn_id=turn.turn_id)
        if (cancelled or completion_status == "cancelled") and not timed_out:
            await repository.mark_run_job_cancelled(job_id=job.id, turn_id=turn.turn_id, now=now_ms_fn())
            await append_audit_log_fn(
                repository=repository,
                bot_id=bot_id,
                chat_id=str(turn.chat_id),
                session_id=turn.session_id,
                action="run.turn",
                result="cancelled",
                detail=f"provider={context.provider}",
                now=now_ms_fn(),
            )
            await streamer.close_turn(turn_id=turn.turn_id)
            return

        if thread_id and not context.routed_provider_changed:
            await repository.set_session_thread_id(session_id=session.session_id, thread_id=thread_id, now=now_ms_fn())

        assistant_text = "\n".join(part.strip() for part in assistant_parts if part.strip()).strip()
        failed = completion_status == "error" or (error_text and not assistant_text)
        failure_result = await apply_failure_policy(
            failed=failed,
            provider=context.provider,
            selected_model=context.selected_model,
            session=session,
            turn=turn,
            bot_id=bot_id,
            repository=repository,
            now_ms_fn=now_ms_fn,
            append_audit_log_fn=append_audit_log_fn,
            looks_like_watchdog_timeout_error_fn=looks_like_watchdog_timeout_error_fn,
            looks_like_gemini_quota_error_fn=looks_like_gemini_quota_error_fn,
            looks_like_gemini_human_input_required_error_fn=looks_like_gemini_human_input_required_error_fn,
            looks_like_codex_access_limited_error_fn=looks_like_codex_access_limited_error_fn,
            timed_out=timed_out,
            routed_provider_changed=context.routed_provider_changed,
            error_text=error_text,
            error_stderr=error_stderr,
            logger=logger,
        )
        error_text = failure_result.error_text
        auto_recovered = failure_result.auto_recovered

        if failed:
            await repository.fail_run_job_and_turn(
                job_id=job.id,
                turn_id=turn.turn_id,
                error_text=error_text or "adapter execution failed",
                now=now_ms_fn(),
            )
            await append_audit_log_fn(
                repository=repository,
                bot_id=bot_id,
                chat_id=str(turn.chat_id),
                session_id=turn.session_id,
                action="run.turn",
                result="failed",
                detail=(
                    f"{(error_text or 'adapter execution failed')[:320]}"
                    f"{' (auto-recovered thread)' if auto_recovered else ''}"
                ),
                now=now_ms_fn(),
            )
            if hasattr(repository, "increment_runtime_metric"):
                try:
                    await repository.increment_runtime_metric(
                        bot_id=bot_id,
                        metric_key=f"provider_run_failed.{context.provider}",
                        now=now_ms_fn(),
                    )
                except Exception:
                    logger.exception(
                        "failed to increment provider failure metric bot=%s provider=%s",
                        bot_id,
                        context.provider,
                    )
        else:
            await repository.complete_run_job_and_turn(
                job_id=job.id,
                turn_id=turn.turn_id,
                assistant_text=assistant_text,
                now=now_ms_fn(),
            )
            await append_audit_log_fn(
                repository=repository,
                bot_id=bot_id,
                chat_id=str(turn.chat_id),
                session_id=turn.session_id,
                action="run.turn",
                result="success",
                detail=f"provider={context.provider}",
                now=now_ms_fn(),
            )
            should_deliver_artifacts = (
                bool(assistant_text)
                or looks_like_image_request_fn(turn.user_text)
                or looks_like_html_request_fn(turn.user_text)
            )
            if should_deliver_artifacts:
                await deliver_generated_artifacts_fn(
                    bot_id=bot_id,
                    chat_id=int(turn.chat_id),
                    turn_id=turn.turn_id,
                    user_text=turn.user_text,
                    assistant_text=assistant_text,
                    run_started_epoch=context.run_started_epoch,
                    artifact_output_dir=context.artifact_output_dir,
                    telegram_client=telegram_client,
                    streamer=streamer,
                    sent_registry=sent_artifacts_by_chat,
                )

        summary = summary_service.build_summary(
            SummaryInput(
                previous_summary=session.rolling_summary_md,
                user_text=turn.user_text,
                assistant_text=assistant_text,
                command_notes=command_notes,
                error_text=error_text,
            )
        )
        await repository.upsert_session_summary(
            session_id=session.session_id,
            bot_id=bot_id,
            turn_id=turn.turn_id,
            summary_md=summary,
            now=now_ms_fn(),
        )

        await streamer.close_turn(turn_id=turn.turn_id)
    except Exception as error:
        logger.exception("run worker failed job=%s", job.id)
        await repository.fail_run_job_and_turn(
            job_id=job.id,
            turn_id=job.turn_id,
            error_text=str(error),
            now=now_ms_fn(),
        )
        with suppress(Exception):
            await streamer.close_turn(turn_id=job.turn_id)
    finally:
        lease_stop.set()
        lease_task.cancel()
        with suppress(asyncio.CancelledError):
            await lease_task
        try:
            promoted = await repository.promote_next_deferred_action(
                bot_id=bot_id,
                chat_id=str(job.chat_id),
                now=now_ms_fn(),
            )
            if promoted is not None:
                logger.info(
                    "promoted deferred action bot=%s chat=%s action=%s turn=%s",
                    bot_id,
                    job.chat_id,
                    promoted.action_type,
                    promoted.turn_id,
                )
        except Exception:
            logger.exception("failed to promote deferred action bot=%s chat=%s", bot_id, job.chat_id)
