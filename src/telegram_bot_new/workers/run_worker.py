from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from telegram_bot_new.adapters import get_adapter
from telegram_bot_new.db.repository import LeasedRunJob, Repository
from telegram_bot_new.model_presets import resolve_selected_model
from telegram_bot_new.routing_policy import suggest_route
from telegram_bot_new.skill_library import build_skill_instruction
from telegram_bot_new.services.summary_service import SummaryService
from telegram_bot_new.streaming.telegram_event_streamer import TelegramEventStreamer
from telegram_bot_new.telegram.client import TelegramApiError, TelegramClient
from telegram_bot_new.workers.run_pipeline.artifact_delivery import deliver_generated_artifacts as _deliver_generated_artifacts_impl
from telegram_bot_new.workers.run_pipeline.job_runner import process_run_job as _process_run_job_impl
from telegram_bot_new.workers.run_pipeline.lease import renew_lease_loop as _renew_lease_loop_impl

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
RUN_TURN_TIMEOUT_SEC = max(15, int(os.getenv("RUN_TURN_TIMEOUT_SEC", "90")))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _looks_like_gemini_quota_error(message: str | None, stderr: str | None) -> bool:
    haystack = " ".join(part for part in [message or "", stderr or ""] if part).lower()
    if not haystack:
        return False
    return any(
        marker in haystack
        for marker in (
            "terminalquotaerror",
            "exhausted your capacity on this model",
            "quota will reset after",
            "api error: you have exhausted your capacity on this model",
        )
    )


def _looks_like_codex_access_limited_error(message: str | None, stderr: str | None) -> bool:
    haystack = " ".join(part for part in [message or "", stderr or ""] if part).lower()
    if not haystack:
        return False
    return any(
        marker in haystack
        for marker in (
            "temporarily limited",
            "potentially suspicious activity",
            "related to cybersecurity",
            "access to gpt-5.3-codex-premium",
        )
    )


def _looks_like_watchdog_timeout_error(message: str | None) -> bool:
    lowered = (message or "").lower()
    if not lowered:
        return False
    return (
        "watchdog timeout" in lowered
        or "turn timed out after" in lowered
        or "adapter stream timed out" in lowered
    )


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


def _safe_path_segment(value: str) -> str:
    lowered = (value or "").strip().lower()
    return re.sub(r"[^a-z0-9._-]+", "_", lowered).strip("._-") or "unknown"


def _build_turn_artifact_output_dir(*, bot_id: str, chat_id: str, turn_id: str) -> Path:
    return (
        Path.cwd()
        / ".mock_messenger"
        / "generated"
        / _safe_path_segment(bot_id)
        / _safe_path_segment(chat_id)
        / _safe_path_segment(turn_id)
    ).resolve()


def _display_path_for_prompt(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(Path.cwd().resolve())
        return f"./{relative.as_posix()}"
    except Exception:
        return str(path.resolve())


def _augment_prompt_for_generation_request(prompt: str, *, artifact_output_dir: Path | None = None) -> str:
    result = prompt
    output_dir = artifact_output_dir.resolve() if artifact_output_dir is not None else None
    output_dir_text = _display_path_for_prompt(output_dir) if output_dir is not None else "./.mock_messenger/generated"
    if _looks_like_image_request(prompt):
        result = (
            f"{result}\n\n[Image Delivery Contract]\n"
            "If you generate an image file, save it as a local file and include at least one markdown image path.\n"
            f"Preferred output directory: {output_dir_text}\n"
            "Preferred format:\n"
            f"![generated]({output_dir_text}/<file>.png)\n"
            "Use a real existing path only."
        )
    if _looks_like_html_request(prompt):
        result = (
            f"{result}\n\n[HTML Delivery Contract]\n"
            "If you generate an HTML page, save it as a local file and include a markdown link to that exact file.\n"
            "Also generate one preview image (png) for Telegram chat preview.\n"
            f"Preferred output directory: {output_dir_text}\n"
            "Preferred formats:\n"
            f"[landing page]({output_dir_text}/<file>.html)\n"
            f"![preview]({output_dir_text}/<file>.png)\n"
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
    return _find_recent_files_in_roots(
        since_epoch=since_epoch,
        suffixes=suffixes,
        scan_roots=[Path.cwd(), Path(tempfile.gettempdir())],
        limit=limit,
    )


def _find_recent_files_in_roots(
    *,
    since_epoch: float,
    suffixes: set[str],
    scan_roots: list[Path],
    limit: int = 3,
) -> list[Path]:
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


async def _append_audit_log(
    *,
    repository: Repository,
    bot_id: str,
    chat_id: str | None,
    session_id: str | None,
    action: str,
    result: str,
    detail: str | None,
    now: int,
) -> None:
    if not hasattr(repository, "append_audit_log"):
        return
    try:
        await repository.append_audit_log(
            bot_id=bot_id,
            chat_id=chat_id,
            session_id=session_id,
            action=action,
            result=result,
            detail_json=detail,
            now=now,
        )
    except Exception:
        LOGGER.exception("failed to append run audit log bot=%s action=%s", bot_id, action)


async def _deliver_generated_artifacts(
    *,
    bot_id: str,
    chat_id: int,
    turn_id: str,
    user_text: str,
    assistant_text: str,
    run_started_epoch: float,
    artifact_output_dir: Path | None = None,
    telegram_client: TelegramClient,
    streamer: TelegramEventStreamer,
    sent_registry: dict[str, set[str]],
) -> None:
    await _deliver_generated_artifacts_impl(
        bot_id=bot_id,
        chat_id=chat_id,
        turn_id=turn_id,
        user_text=user_text,
        assistant_text=assistant_text,
        run_started_epoch=run_started_epoch,
        artifact_output_dir=artifact_output_dir,
        telegram_client=telegram_client,
        streamer=streamer,
        sent_registry=sent_registry,
        image_suffixes=IMAGE_SUFFIXES,
        html_suffixes=HTML_SUFFIXES,
        extract_local_paths_fn=_extract_local_paths,
        find_recent_files_fn=_find_recent_files,
        find_recent_files_in_roots_fn=_find_recent_files_in_roots,
        artifact_dedupe_key_fn=_artifact_dedupe_key,
        looks_like_image_request_fn=_looks_like_image_request,
        looks_like_html_request_fn=_looks_like_html_request,
        telegram_api_error_type=TelegramApiError,
        logger=LOGGER,
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
    await _process_run_job_impl(
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
        renew_lease_loop=_renew_lease_loop,
        now_ms_fn=_now_ms,
        get_adapter_fn=get_adapter,
        suggest_route_fn=suggest_route,
        resolve_selected_model_fn=resolve_selected_model,
        build_skill_instruction_fn=build_skill_instruction,
        append_audit_log_fn=_append_audit_log,
        build_turn_artifact_output_dir_fn=_build_turn_artifact_output_dir,
        augment_prompt_for_generation_request_fn=_augment_prompt_for_generation_request,
        looks_like_watchdog_timeout_error_fn=_looks_like_watchdog_timeout_error,
        looks_like_gemini_quota_error_fn=_looks_like_gemini_quota_error,
        looks_like_codex_access_limited_error_fn=_looks_like_codex_access_limited_error,
        looks_like_image_request_fn=_looks_like_image_request,
        looks_like_html_request_fn=_looks_like_html_request,
        deliver_generated_artifacts_fn=_deliver_generated_artifacts,
        run_turn_timeout_sec=RUN_TURN_TIMEOUT_SEC,
        logger=LOGGER,
    )


async def _renew_lease_loop(*, job_id: str, repository: Repository, lease_ms: int, stop_event: asyncio.Event) -> None:
    await _renew_lease_loop_impl(
        job_id=job_id,
        repository=repository,
        lease_ms=lease_ms,
        stop_event=stop_event,
        now_ms_fn=_now_ms,
    )
