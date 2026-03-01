from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from telegram_bot_new.telegram.poller import run_telegram_poller


@pytest.mark.asyncio
async def test_run_telegram_poller_enqueues_new_updates() -> None:
    stop_event = asyncio.Event()
    calls = 0

    async def _get_updates(*, offset, timeout_sec, limit):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            assert offset is None
            return [{"update_id": 101, "message": {"chat": {"id": 777}}}]
        stop_event.set()
        return []

    repository = SimpleNamespace(
        insert_telegram_update=AsyncMock(return_value=True),
        enqueue_telegram_update_job=AsyncMock(),
    )
    client = SimpleNamespace(
        delete_webhook=AsyncMock(),
        get_updates=AsyncMock(side_effect=_get_updates),
    )

    await run_telegram_poller(
        bot_id="bot-a",
        repository=repository,
        client=client,
        poll_interval_ms=50,
        stop_event=stop_event,
    )

    client.delete_webhook.assert_awaited_once_with(drop_pending_updates=False)
    repository.insert_telegram_update.assert_awaited_once()
    repository.enqueue_telegram_update_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_telegram_poller_skips_invalid_update_id() -> None:
    stop_event = asyncio.Event()
    calls = 0

    async def _get_updates(*, offset, timeout_sec, limit):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"update_id": "oops"}, {"message": {"chat": {"id": 777}}}]
        stop_event.set()
        return []

    repository = SimpleNamespace(
        insert_telegram_update=AsyncMock(return_value=True),
        enqueue_telegram_update_job=AsyncMock(),
    )
    client = SimpleNamespace(
        delete_webhook=AsyncMock(),
        get_updates=AsyncMock(side_effect=_get_updates),
    )

    await run_telegram_poller(
        bot_id="bot-a",
        repository=repository,
        client=client,
        poll_interval_ms=50,
        stop_event=stop_event,
    )

    repository.insert_telegram_update.assert_not_awaited()
    repository.enqueue_telegram_update_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_telegram_poller_does_not_enqueue_duplicate_update() -> None:
    stop_event = asyncio.Event()
    calls = 0

    async def _get_updates(*, offset, timeout_sec, limit):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"update_id": 102, "message": {"chat": {"id": 888}}}]
        stop_event.set()
        return []

    repository = SimpleNamespace(
        insert_telegram_update=AsyncMock(return_value=False),
        enqueue_telegram_update_job=AsyncMock(),
    )
    client = SimpleNamespace(
        delete_webhook=AsyncMock(),
        get_updates=AsyncMock(side_effect=_get_updates),
    )

    await run_telegram_poller(
        bot_id="bot-b",
        repository=repository,
        client=client,
        poll_interval_ms=50,
        stop_event=stop_event,
    )

    repository.insert_telegram_update.assert_awaited_once()
    repository.enqueue_telegram_update_job.assert_not_awaited()
