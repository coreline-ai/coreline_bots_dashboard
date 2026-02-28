from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import suppress

from telegram_bot_new.db.repository import LeasedTelegramUpdateJob, Repository
from telegram_bot_new.telegram.commands import TelegramCommandHandler

LOGGER = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


async def run_update_worker(
    *,
    bot_id: str,
    repository: Repository,
    handler: TelegramCommandHandler,
    lease_ms: int,
    poll_interval_ms: int,
    stop_event: asyncio.Event,
) -> None:
    owner = f"update-worker:{bot_id}:{os.getpid()}"
    heartbeat_interval_ms = 5000
    next_heartbeat_ms = 0

    while not stop_event.is_set():
        now = _now_ms()
        try:
            if now >= next_heartbeat_ms:
                await repository.increment_runtime_metric(
                    bot_id=bot_id,
                    metric_key="worker_heartbeat.update_worker",
                    now=now,
                )
                next_heartbeat_ms = now + heartbeat_interval_ms

            job = await repository.lease_next_telegram_update_job(
                bot_id=bot_id,
                owner=owner,
                now=now,
                lease_duration_ms=lease_ms,
            )
            if job is None:
                await asyncio.sleep(poll_interval_ms / 1000)
                continue

            await _process_job(
                job=job,
                bot_id=bot_id,
                repository=repository,
                handler=handler,
                lease_ms=lease_ms,
                stop_event=stop_event,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("update worker loop error bot=%s", bot_id)
            await asyncio.sleep(1)


async def _process_job(
    *,
    job: LeasedTelegramUpdateJob,
    bot_id: str,
    repository: Repository,
    handler: TelegramCommandHandler,
    lease_ms: int,
    stop_event: asyncio.Event,
) -> None:
    lease_stop = asyncio.Event()
    lease_task = asyncio.create_task(
        _renew_lease_loop(
            job_id=job.id,
            repository=repository,
            lease_ms=lease_ms,
            stop_event=lease_stop,
        )
    )

    try:
        update_row = await repository.get_telegram_update(bot_id=bot_id, update_id=job.update_id)
        if update_row is None:
            await repository.fail_telegram_update_job(job_id=job.id, now=_now_ms(), error="missing telegram update row")
            return

        try:
            payload = json.loads(update_row.payload_json)
        except json.JSONDecodeError as error:
            await repository.fail_telegram_update_job(job_id=job.id, now=_now_ms(), error=f"invalid payload json: {error}")
            return

        if not isinstance(payload, dict):
            await repository.fail_telegram_update_job(job_id=job.id, now=_now_ms(), error="payload must be object")
            return

        await handler.handle_update_payload(payload, _now_ms())
        await repository.complete_telegram_update_job(job_id=job.id, now=_now_ms())
    except Exception as error:
        LOGGER.exception("failed update job bot=%s update_id=%s", bot_id, job.update_id)
        await repository.fail_telegram_update_job(job_id=job.id, now=_now_ms(), error=str(error)[:2000])
    finally:
        lease_stop.set()
        lease_task.cancel()
        with suppress(asyncio.CancelledError):
            await lease_task


async def _renew_lease_loop(*, job_id: str, repository: Repository, lease_ms: int, stop_event: asyncio.Event) -> None:
    interval = max(1.0, lease_ms / 2000)
    while not stop_event.is_set():
        await asyncio.sleep(interval)
        if stop_event.is_set():
            return
        await repository.renew_telegram_update_job_lease(job_id=job_id, now=_now_ms(), lease_duration_ms=lease_ms)
