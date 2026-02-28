from __future__ import annotations

import pytest

from telegram_bot_new.adapters.base import AdapterEvent
from telegram_bot_new.streaming.telegram_event_streamer import MAX_MESSAGE_LEN, TelegramEventStreamer
from telegram_bot_new.telegram.client import TelegramRateLimitError


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str | None]] = []
        self.edited: list[tuple[int, int, str, str | None]] = []
        self._next_message_id = 1
        self.fail_send_once = False

    async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None) -> int:
        if self.fail_send_once:
            self.fail_send_once = False
            raise TelegramRateLimitError(retry_after=1)
        message_id = self._next_message_id
        self._next_message_id += 1
        self.sent.append((chat_id, text, parse_mode))
        return message_id

    async def edit_message(self, chat_id: int, message_id: int, text: str, parse_mode: str | None = None) -> None:
        self.edited.append((chat_id, message_id, text, parse_mode))


@pytest.mark.asyncio
async def test_streamer_edits_same_message_until_limit() -> None:
    client = FakeClient()
    streamer = TelegramEventStreamer(client)

    event1 = AdapterEvent(seq=1, ts="2026-01-01T00:00:00+00:00", event_type="reasoning", payload={"text": "a"})
    event2 = AdapterEvent(seq=2, ts="2026-01-01T00:00:01+00:00", event_type="reasoning", payload={"text": "b"})

    await streamer.append_event(turn_id="t1", chat_id=100, event=event1)
    await streamer.append_event(turn_id="t1", chat_id=100, event=event2)

    assert len(client.sent) == 1
    assert len(client.edited) == 1


@pytest.mark.asyncio
async def test_streamer_creates_continuation_when_message_too_long() -> None:
    client = FakeClient()
    streamer = TelegramEventStreamer(client)

    long_text = "x" * (MAX_MESSAGE_LEN - 20)
    for seq in range(1, 6):
        event = AdapterEvent(
            seq=seq,
            ts="2026-01-01T00:00:00+00:00",
            event_type="assistant_message",
            payload={"text": long_text},
        )
    await streamer.append_event(turn_id="t2", chat_id=100, event=event)

    assert len(client.sent) >= 2
    assert any(text.startswith("[continued]") for _, text, _ in client.sent[1:])


@pytest.mark.asyncio
async def test_streamer_retries_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    client.fail_send_once = True
    streamer = TelegramEventStreamer(client)

    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("telegram_bot_new.streaming.telegram_event_streamer.asyncio.sleep", fake_sleep)

    event = AdapterEvent(seq=1, ts="2026-01-01T00:00:00+00:00", event_type="reasoning", payload={"text": "hello"})
    await streamer.append_event(turn_id="t3", chat_id=100, event=event)

    assert len(client.sent) == 1


@pytest.mark.asyncio
async def test_streamer_renders_fenced_code_block_with_html_parse_mode() -> None:
    client = FakeClient()
    streamer = TelegramEventStreamer(client)

    event = AdapterEvent(
        seq=1,
        ts="2026-01-01T00:00:00+00:00",
        event_type="assistant_message",
        payload={"text": "예시 코드:\n```python\nprint('hi')\n```"},
    )
    await streamer.append_event(turn_id="t4", chat_id=100, event=event)

    assert len(client.sent) == 1
    _, text, parse_mode = client.sent[0]
    assert parse_mode == "HTML"
    assert "<pre><code class=\"language-python\">" in text
    assert "print(&#x27;hi&#x27;)" in text
