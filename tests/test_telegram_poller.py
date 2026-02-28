from __future__ import annotations

import asyncio

import pytest

from telegram_bot_new.telegram.poller import run_telegram_poller


class FakeRepository:
    def __init__(self, max_update_id: int | None) -> None:
        self.max_update_id = max_update_id
        self.max_id_calls = 0

    async def get_max_telegram_update_id(self, *, bot_id: str) -> int | None:
        self.max_id_calls += 1
        return self.max_update_id

    async def insert_telegram_update(self, **kwargs) -> bool:  # pragma: no cover
        return False

    async def enqueue_telegram_update_job(self, **kwargs) -> None:  # pragma: no cover
        return None


class FakeTelegramClient:
    def __init__(self, stop_event: asyncio.Event) -> None:
        self.stop_event = stop_event
        self.offsets: list[int | None] = []
        self.delete_webhook_calls = 0

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        self.delete_webhook_calls += 1

    async def get_updates(self, *, offset: int | None = None, timeout_sec: int = 25, limit: int = 100):
        self.offsets.append(offset)
        self.stop_event.set()
        return []


@pytest.mark.asyncio
async def test_poller_uses_persisted_offset_by_default() -> None:
    stop_event = asyncio.Event()
    repository = FakeRepository(max_update_id=42)
    client = FakeTelegramClient(stop_event)

    await asyncio.wait_for(
        run_telegram_poller(
            bot_id="bot-1",
            repository=repository,
            client=client,
            poll_interval_ms=0,
            stop_event=stop_event,
        ),
        timeout=1,
    )

    assert repository.max_id_calls == 1
    assert client.delete_webhook_calls == 1
    assert client.offsets
    assert client.offsets[0] == 43


@pytest.mark.asyncio
async def test_poller_ignores_persisted_offset_when_requested() -> None:
    stop_event = asyncio.Event()
    repository = FakeRepository(max_update_id=42)
    client = FakeTelegramClient(stop_event)

    await asyncio.wait_for(
        run_telegram_poller(
            bot_id="bot-1",
            repository=repository,
            client=client,
            poll_interval_ms=0,
            stop_event=stop_event,
            ignore_persisted_offset=True,
        ),
        timeout=1,
    )

    assert repository.max_id_calls == 0
    assert client.delete_webhook_calls == 1
    assert client.offsets
    assert client.offsets[0] is None
