from __future__ import annotations

import asyncio
from collections.abc import Callable

from telegram_bot_new.db.repository import Repository


async def renew_lease_loop(
    *,
    job_id: str,
    repository: Repository,
    lease_ms: int,
    stop_event: asyncio.Event,
    now_ms_fn: Callable[[], int],
) -> None:
    interval = max(1.0, lease_ms / 2000)
    while not stop_event.is_set():
        await asyncio.sleep(interval)
        if stop_event.is_set():
            return
        await repository.renew_run_job_lease(job_id=job_id, now=now_ms_fn(), lease_duration_ms=lease_ms)
