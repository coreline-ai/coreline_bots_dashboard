from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from telegram_bot_new.adapters import get_adapter
from telegram_bot_new.adapters.base import AdapterEvent, AdapterResumeRequest, AdapterRunRequest, utc_now_iso
from telegram_bot_new.db.repository import LeasedRunJob, Repository
from telegram_bot_new.services.summary_service import SummaryInput, SummaryService
from telegram_bot_new.streaming.telegram_event_streamer import TelegramEventStreamer
from telegram_bot_new.telegram.client import TelegramApiError, TelegramClient

LOGGER = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
HTML_SUFFIXES = {".html", ".htm"}
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _looks_like_image_request(prompt: str) -> bool:
    text = (prompt or "").lower()
    if not text:
        return False
    keywords = [
        "image",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "photo",
        "diagram",
        "chart",
        "plot",
        "figure",
        "draw",
        "render",
        "\uc774\ubbf8\uc9c0",
        "\uc0ac\uc9c4",
        "\uadf8\ub9bc",
        "\ucc28\ud2b8",
        "\uadf8\ub798\ud504",
    ]
    return any(keyword in text for keyword in keywords)


def _looks_like_html_request(prompt: str) -> bool:
    text = (prompt or "").lower()
    if not text:
        return False
    keywords = [
        "html",
        "css",
        "landing page",
        "web page",
        "webpage",
        "site",
        "\ub79c\ub529",
        "\uc6f9\ud398\uc774\uc9c0",
        "\ud398\uc774\uc9c0",
    ]
    return any(keyword in text for keyword in keywords)


def _augment_prompt_for_generation_request(prompt: str) -> str:
    result = prompt
    if _looks_like_image_request(prompt):
        result = (
            f"{result}\n\n[Image Delivery Contract]\n"
            "If you generate an image file, save it as a local file and include at least one markdown image path.\n"
            "Preferred format:\n"
            "![generated](./.mock_messenger/generated/<file>.png)\n"
            "Use a real existing path only."
        )
    if _looks_like_html_request(prompt):
        result = (
            f"{result}\n\n[HTML Delivery Contract]\n"
            "If you generate an HTML page, save it as a local file and include a markdown link to that exact file.\n"
            "Also generate one preview image (png) for Telegram chat preview.\n"
            "Preferred formats:\n"
            "[landing page](./.mock_messenger/generated/<file>.html)\n"
            "![preview](./.mock_messenger/generated/<file>.png)\n"
            "Use inline CSS if possible so single-file preview works."
        )
    return result


def _extract_local_paths(text: str, *, suffixes: set[str]) -> list[Path]:
    if not text or not text.strip():
        return []

    suffix_pattern = "|".join(ext.lstrip(".") for ext in sorted(suffixes))
    candidates: list[str] = []
    candidates.extend(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text))
    candidates.extend(re.findall(r"\[[^\]]*\]\(([^)]+)\)", text))
    candidates.extend(
        re.findall(
            rf"['\"]([^'\"]+\.(?:{suffix_pattern}))['\"]",
            text,
            flags=re.IGNORECASE,
        )
    )
    candidates.extend(
        re.findall(
            rf"((?:[A-Za-z]:)?(?:[./\\][^\s'\"`<>|]+)+\.(?:{suffix_pattern}))",
            text,
            flags=re.IGNORECASE,
        )
    )

    paths: list[Path] = []
    seen: set[str] = set()
    for raw in candidates:
        candidate = raw.strip().strip("\"'").strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("data:"):
            continue
        resolved = Path(candidate).expanduser()
        if not resolved.is_absolute():
            resolved = (Path.cwd() / resolved).resolve()
        else:
            resolved = resolved.resolve()
        if resolved.suffix.lower() not in suffixes:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        if resolved.exists() and resolved.is_file():
            seen.add(key)
            paths.append(resolved)
    return paths


def _find_recent_files(*, since_epoch: float, suffixes: set[str], limit: int = 3) -> list[Path]:
    scan_roots = [Path.cwd(), Path(tempfile.gettempdir())]
    discovered: list[tuple[float, Path]] = []
    seen: set[str] = set()
    cutoff = since_epoch - 2.0

    for root in scan_roots:
        try:
            resolved_root = root.resolve()
        except Exception:
            continue
        if not resolved_root.exists() or not resolved_root.is_dir():
            continue

        for dirpath, dirnames, filenames in os.walk(resolved_root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
            for name in filenames:
                suffix = Path(name).suffix.lower()
                if suffix not in suffixes:
                    continue
                path = Path(dirpath) / name
                key = str(path).lower()
                if key in seen:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size <= 0 or stat.st_mtime < cutoff:
                    continue
                seen.add(key)
                discovered.append((stat.st_mtime, path.resolve()))

    discovered.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in discovered[: max(1, limit)]]


def _artifact_dedupe_key(path: Path) -> str:
    resolved = path.resolve()
    try:
        stat = resolved.stat()
        return f"{str(resolved).lower()}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return str(resolved).lower()


async def _deliver_generated_artifacts(
    *,
    bot_id: str,
    chat_id: int,
    turn_id: str,
    user_text: str,
    assistant_text: str,
    run_started_epoch: float,
    telegram_client: TelegramClient,
    streamer: TelegramEventStreamer,
    sent_registry: dict[str, set[str]],
) -> None:
    image_paths = _extract_local_paths(assistant_text, suffixes=IMAGE_SUFFIXES)
    html_paths = _extract_local_paths(assistant_text, suffixes=HTML_SUFFIXES)

    if not image_paths and _looks_like_image_request(user_text):
        image_paths = _find_recent_files(since_epoch=run_started_epoch, suffixes=IMAGE_SUFFIXES, limit=3)
    if not html_paths and _looks_like_html_request(user_text):
        html_paths = _find_recent_files(since_epoch=run_started_epoch, suffixes=HTML_SUFFIXES, limit=2)

    unique_files: list[tuple[Path, str]] = []
    sent_for_chat = sent_registry.setdefault(f"{bot_id}:{chat_id}", set())

    for image_path in image_paths:
        key = _artifact_dedupe_key(image_path)
        if key in sent_for_chat:
            continue
        sent_for_chat.add(key)
        unique_files.append((image_path, "image"))

    for html_path in html_paths:
        key = _artifact_dedupe_key(html_path)
        if key in sent_for_chat:
            continue
        sent_for_chat.add(key)
        unique_files.append((html_path, "html"))

    for path, kind in unique_files:
        try:
            if kind == "image":
                try:
                    await telegram_client.send_photo(
                        chat_id=chat_id,
                        file_path=str(path),
                        caption=f"[artifact:image] {path.name}",
                    )
                except TelegramApiError:
                    await telegram_client.send_document(
                        chat_id=chat_id,
                        file_path=str(path),
                        caption=f"[artifact:image] {path.name}",
                    )
            else:
                await telegram_client.send_document(
                    chat_id=chat_id,
                    file_path=str(path),
                    caption=f"[artifact:html] {path.name}",
                )
        except Exception as error:
            LOGGER.warning("artifact delivery failed bot=%s chat=%s path=%s err=%s", bot_id, chat_id, path, error)
            await streamer.append_delivery_error(
                turn_id=turn_id,
                chat_id=chat_id,
                message=f"artifact delivery failed for {path.name}: {error}",
            )


async def run_cli_worker(
    *,
    bot_id: str,
    repository: Repository,
    telegram_client: TelegramClient,
    streamer: TelegramEventStreamer,
    summary_service: SummaryService,
    default_models_by_provider: dict[str, str | None],
    default_sandbox: str,
    lease_ms: int,
    poll_interval_ms: int,
    stop_event: asyncio.Event,
) -> None:
    owner = f"run-worker:{bot_id}:{os.getpid()}"
    sent_artifacts_by_chat: dict[str, set[str]] = {}
    heartbeat_interval_ms = 5000
    next_heartbeat_ms = 0

    while not stop_event.is_set():
        now = _now_ms()
        try:
            if now >= next_heartbeat_ms:
                await repository.increment_runtime_metric(
                    bot_id=bot_id,
                    metric_key="worker_heartbeat.run_worker",
                    now=now,
                )
                next_heartbeat_ms = now + heartbeat_interval_ms

            job = await repository.lease_next_run_job(
                bot_id=bot_id,
                owner=owner,
                now=now,
                lease_duration_ms=lease_ms,
            )
            if job is None:
                await asyncio.sleep(poll_interval_ms / 1000)
                continue

            await _process_run_job(
                job=job,
                bot_id=bot_id,
                repository=repository,
                telegram_client=telegram_client,
                streamer=streamer,
                summary_service=summary_service,
                default_models_by_provider=default_models_by_provider,
                default_sandbox=default_sandbox,
                lease_ms=lease_ms,
                sent_artifacts_by_chat=sent_artifacts_by_chat,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("run worker loop error bot=%s", bot_id)
            await asyncio.sleep(1)


async def _process_run_job(
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
) -> None:
    lease_stop = asyncio.Event()
    lease_task = asyncio.create_task(
        _renew_lease_loop(job_id=job.id, repository=repository, lease_ms=lease_ms, stop_event=lease_stop)
    )

    try:
        turn = await repository.get_turn(turn_id=job.turn_id)
        if turn is None:
            await repository.fail_run_job_and_turn(job_id=job.id, turn_id=job.turn_id, error_text="missing turn", now=_now_ms())
            return

        session = await repository.get_session_view(session_id=turn.session_id)
        if session is None:
            await repository.fail_run_job_and_turn(job_id=job.id, turn_id=job.turn_id, error_text="missing session", now=_now_ms())
            return

        await repository.mark_run_in_flight(job_id=job.id, turn_id=turn.turn_id, now=_now_ms())

        provider = session.adapter_name
        adapter = get_adapter(provider)
        preamble = summary_service.build_recovery_preamble(session.rolling_summary_md)
        run_started_epoch = time.time()
        execution_prompt = _augment_prompt_for_generation_request(turn.user_text)
        selected_model = default_models_by_provider.get(provider)
        selected_sandbox = default_sandbox if provider == "codex" else ""

        async def should_cancel() -> bool:
            return await repository.is_turn_cancelled(turn_id=turn.turn_id)

        if session.adapter_thread_id:
            stream = adapter.run_resume_turn(
                AdapterResumeRequest(
                    thread_id=session.adapter_thread_id,
                    prompt=execution_prompt,
                    model=selected_model,
                    sandbox=selected_sandbox,
                    preamble=preamble,
                    should_cancel=should_cancel,
                )
            )
        else:
            stream = adapter.run_new_turn(
                AdapterRunRequest(
                    prompt=execution_prompt,
                    model=selected_model,
                    sandbox=selected_sandbox,
                    preamble=preamble,
                    should_cancel=should_cancel,
                )
            )

        # If this turn was partially processed before a worker restart/crash,
        # continue with the next sequence number to avoid unique key conflicts.
        seq = (await repository.get_turn_events_count(turn_id=turn.turn_id)) + 1
        assistant_parts: list[str] = []
        command_notes: list[str] = []
        thread_id: str | None = None
        completion_status = "success"
        error_text: str | None = None

        async def _persist_and_stream_event(event: AdapterEvent) -> None:
            nonlocal seq
            await repository.append_cli_event(
                turn_id=turn.turn_id,
                bot_id=bot_id,
                seq=event.seq,
                event_type=event.event_type,
                payload_json=json.dumps({"ts": event.ts, "payload": event.payload}, ensure_ascii=False),
                now=_now_ms(),
            )
            try:
                await streamer.append_event(turn_id=turn.turn_id, chat_id=int(turn.chat_id), event=event)
            except Exception as stream_error:
                seq += 1
                await repository.append_cli_event(
                    turn_id=turn.turn_id,
                    bot_id=bot_id,
                    seq=seq,
                    event_type="delivery_error",
                    payload_json=json.dumps({"message": str(stream_error)}),
                    now=_now_ms(),
                )

        try:
            async for raw_event in stream:
                event = AdapterEvent(seq=seq, ts=raw_event.ts, event_type=raw_event.event_type, payload=raw_event.payload)
                await _persist_and_stream_event(event)

                if event.event_type == "assistant_message":
                    text = event.payload.get("text")
                    if isinstance(text, str) and text.strip():
                        assistant_parts.append(text)

                if event.event_type in ("command_started", "command_completed"):
                    cmd = event.payload.get("command")
                    if isinstance(cmd, str) and cmd:
                        command_notes.append(cmd)

                if event.event_type == "thread_started":
                    candidate = adapter.extract_thread_id(event)
                    if candidate:
                        thread_id = candidate

                if event.event_type == "turn_completed":
                    status = event.payload.get("status")
                    if isinstance(status, str):
                        completion_status = status

                if event.event_type == "error" and error_text is None:
                    msg = event.payload.get("message")
                    if isinstance(msg, str):
                        error_text = msg

                seq += 1
        except FileNotFoundError:
            error_text = f"provider={provider} executable not found; install CLI or switch with /mode codex"
            completion_status = "error"
            await _persist_and_stream_event(
                AdapterEvent(
                    seq=seq,
                    ts=utc_now_iso(),
                    event_type="error",
                    payload={"message": error_text},
                )
            )
            seq += 1
            await _persist_and_stream_event(
                AdapterEvent(
                    seq=seq,
                    ts=utc_now_iso(),
                    event_type="turn_completed",
                    payload={"status": "error"},
                )
            )
            seq += 1
        except Exception as stream_error:
            error_text = str(stream_error)
            completion_status = "error"
            await _persist_and_stream_event(
                AdapterEvent(
                    seq=seq,
                    ts=utc_now_iso(),
                    event_type="error",
                    payload={"message": error_text},
                )
            )
            seq += 1
            await _persist_and_stream_event(
                AdapterEvent(
                    seq=seq,
                    ts=utc_now_iso(),
                    event_type="turn_completed",
                    payload={"status": "error"},
                )
            )
            seq += 1

        cancelled = await repository.is_turn_cancelled(turn_id=turn.turn_id)
        if cancelled or completion_status == "cancelled":
            await repository.mark_run_job_cancelled(job_id=job.id, turn_id=turn.turn_id, now=_now_ms())
            await streamer.close_turn(turn_id=turn.turn_id)
            return

        if thread_id:
            await repository.set_session_thread_id(session_id=session.session_id, thread_id=thread_id, now=_now_ms())

        assistant_text = "\n".join(part.strip() for part in assistant_parts if part.strip()).strip()
        failed = completion_status == "error" or (error_text and not assistant_text)
        if failed:
            await repository.fail_run_job_and_turn(
                job_id=job.id,
                turn_id=turn.turn_id,
                error_text=error_text or "adapter execution failed",
                now=_now_ms(),
            )
            if hasattr(repository, "increment_runtime_metric"):
                try:
                    await repository.increment_runtime_metric(
                        bot_id=bot_id,
                        metric_key=f"provider_run_failed.{provider}",
                        now=_now_ms(),
                    )
                except Exception:
                    LOGGER.exception("failed to increment provider failure metric bot=%s provider=%s", bot_id, provider)
        else:
            await repository.complete_run_job_and_turn(
                job_id=job.id,
                turn_id=turn.turn_id,
                assistant_text=assistant_text,
                now=_now_ms(),
            )
            should_deliver_artifacts = (
                bool(assistant_text)
                or _looks_like_image_request(turn.user_text)
                or _looks_like_html_request(turn.user_text)
            )
            if should_deliver_artifacts:
                await _deliver_generated_artifacts(
                    bot_id=bot_id,
                    chat_id=int(turn.chat_id),
                    turn_id=turn.turn_id,
                    user_text=turn.user_text,
                    assistant_text=assistant_text,
                    run_started_epoch=run_started_epoch,
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
            now=_now_ms(),
        )

        await streamer.close_turn(turn_id=turn.turn_id)
    except Exception as error:
        LOGGER.exception("run worker failed job=%s", job.id)
        await repository.fail_run_job_and_turn(
            job_id=job.id,
            turn_id=job.turn_id,
            error_text=str(error),
            now=_now_ms(),
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
                now=_now_ms(),
            )
            if promoted is not None:
                LOGGER.info(
                    "promoted deferred action bot=%s chat=%s action=%s turn=%s",
                    bot_id,
                    job.chat_id,
                    promoted.action_type,
                    promoted.turn_id,
                )
        except Exception:
            LOGGER.exception("failed to promote deferred action bot=%s chat=%s", bot_id, job.chat_id)


async def _renew_lease_loop(*, job_id: str, repository: Repository, lease_ms: int, stop_event: asyncio.Event) -> None:
    interval = max(1.0, lease_ms / 2000)
    while not stop_event.is_set():
        await asyncio.sleep(interval)
        if stop_event.is_set():
            return
        await repository.renew_run_job_lease(job_id=job_id, now=_now_ms(), lease_duration_ms=lease_ms)
