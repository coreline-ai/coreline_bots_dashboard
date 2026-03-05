from __future__ import annotations

import asyncio
from typing import Any

import pytest

import telegram_bot_new.workers.run_worker as run_worker_module
from telegram_bot_new.db.repository import LeasedRunJob
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


class _RunConcurrencyRepo:
    def __init__(self, jobs: list[LeasedRunJob]) -> None:
        self._jobs = list(jobs)

    async def increment_runtime_metric(self, *, bot_id: str, metric_key: str, now: int, delta: int = 1) -> None:
        return None

    async def lease_next_run_job(
        self,
        *,
        bot_id: str,
        owner: str,
        now: int,
        lease_duration_ms: int,
    ) -> LeasedRunJob | None:
        if self._jobs:
            return self._jobs.pop(0)
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


@pytest.mark.asyncio
async def test_run_worker_uses_configured_concurrency_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    stop_event = asyncio.Event()
    repository = _RunConcurrencyRepo(
        [
            LeasedRunJob(id="job-1", turn_id="turn-1", chat_id="1001"),
            LeasedRunJob(id="job-2", turn_id="turn-2", chat_id="1002"),
        ]
    )
    current = 0
    peak = 0
    completed = 0

    async def _fake_process_run_job(**_kwargs: Any) -> None:
        nonlocal current, peak, completed
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        completed += 1
        if completed >= 2:
            stop_event.set()

    monkeypatch.setattr(run_worker_module, "RUN_WORKER_CONCURRENCY", 2)
    monkeypatch.setattr(run_worker_module, "_process_run_job", _fake_process_run_job)

    await run_cli_worker(
        bot_id="bot-a",
        repository=repository,  # type: ignore[arg-type]
        telegram_client=object(),  # not used in fake processor
        streamer=object(),  # not used in fake processor
        summary_service=object(),  # not used in fake processor
        default_models_by_provider={"codex": None, "gemini": None, "claude": None},
        default_sandbox="workspace-write",
        lease_ms=1000,
        poll_interval_ms=1,
        stop_event=stop_event,
    )

    assert peak == 2
