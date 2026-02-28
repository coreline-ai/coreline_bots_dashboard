from __future__ import annotations

import asyncio
from typing import Any

import pytest

from telegram_bot_new.workers.run_worker import run_cli_worker
from telegram_bot_new.workers.update_worker import run_update_worker


class _RunHeartbeatRepo:
    def __init__(self, stop_event: asyncio.Event) -> None:
        self.stop_event = stop_event
        self.metric_keys: list[str] = []
        self._leased = False

    async def increment_runtime_metric(self, *, bot_id: str, metric_key: str, now: int, delta: int = 1) -> None:
        self.metric_keys.append(metric_key)

    async def lease_next_run_job(
        self,
        *,
        bot_id: str,
        owner: str,
        now: int,
        lease_duration_ms: int,
    ) -> None:
        if not self._leased:
            self._leased = True
            self.stop_event.set()
        return None


class _UpdateHeartbeatRepo:
    def __init__(self, stop_event: asyncio.Event) -> None:
        self.stop_event = stop_event
        self.metric_keys: list[str] = []
        self._leased = False

    async def increment_runtime_metric(self, *, bot_id: str, metric_key: str, now: int, delta: int = 1) -> None:
        self.metric_keys.append(metric_key)

    async def lease_next_telegram_update_job(
        self,
        *,
        bot_id: str,
        owner: str,
        now: int,
        lease_duration_ms: int,
    ) -> None:
        if not self._leased:
            self._leased = True
            self.stop_event.set()
        return None


@pytest.mark.asyncio
async def test_run_worker_increments_heartbeat_metric() -> None:
    stop_event = asyncio.Event()
    repository = _RunHeartbeatRepo(stop_event)

    await run_cli_worker(
        bot_id="bot-a",
        repository=repository,  # type: ignore[arg-type]
        telegram_client=object(),  # not used when no job
        streamer=object(),  # not used when no job
        summary_service=object(),  # not used when no job
        default_models_by_provider={"codex": None, "gemini": None, "claude": None},
        default_sandbox="workspace-write",
        lease_ms=1000,
        poll_interval_ms=1,
        stop_event=stop_event,
    )

    assert "worker_heartbeat.run_worker" in repository.metric_keys


@pytest.mark.asyncio
async def test_update_worker_increments_heartbeat_metric() -> None:
    stop_event = asyncio.Event()
    repository = _UpdateHeartbeatRepo(stop_event)

    await run_update_worker(
        bot_id="bot-a",
        repository=repository,  # type: ignore[arg-type]
        handler=object(),  # not used when no job
        lease_ms=1000,
        poll_interval_ms=1,
        stop_event=stop_event,
    )

    assert "worker_heartbeat.update_worker" in repository.metric_keys
