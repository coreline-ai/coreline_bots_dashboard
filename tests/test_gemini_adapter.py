import pytest

from telegram_bot_new.adapters.base import AdapterResumeRequest, AdapterRunRequest
from telegram_bot_new.adapters.gemini_adapter import GeminiAdapter


@pytest.mark.asyncio
async def test_run_new_turn_builds_expected_gemini_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    async def fake_run_process(self: GeminiAdapter, args: list[str], should_cancel):
        captured["args"] = args
        if False:
            yield

    monkeypatch.setattr(GeminiAdapter, "_run_process", fake_run_process)

    adapter = GeminiAdapter(gemini_bin="gemini")
    request = AdapterRunRequest(
        prompt="hello",
        model="gemini-2.5-pro",
        preamble="memory",
    )

    events = [event async for event in adapter.run_new_turn(request)]

    assert events == []
    assert captured["args"] == [
        "gemini",
        "--approval-mode",
        "yolo",
        "-o",
        "stream-json",
        "--model",
        "gemini-2.5-pro",
        "memory\n\n[User Message]\nhello",
    ]


@pytest.mark.asyncio
async def test_run_resume_turn_builds_expected_gemini_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    async def fake_run_process(self: GeminiAdapter, args: list[str], should_cancel):
        captured["args"] = args
        if False:
            yield

    monkeypatch.setattr(GeminiAdapter, "_run_process", fake_run_process)

    adapter = GeminiAdapter(gemini_bin="gemini")
    request = AdapterResumeRequest(
        thread_id="g-session-1",
        prompt="continue",
        model="gemini-2.5-flash",
        preamble="memory",
    )

    events = [event async for event in adapter.run_resume_turn(request)]

    assert events == []
    assert captured["args"] == [
        "gemini",
        "--resume",
        "g-session-1",
        "--approval-mode",
        "yolo",
        "-o",
        "stream-json",
        "--model",
        "gemini-2.5-flash",
        "memory\n\n[User Message]\ncontinue",
    ]


def test_normalize_gemini_events() -> None:
    adapter = GeminiAdapter()

    init_events = adapter.normalize_event(
        '{"type":"init","session_id":"sid-1","model":"auto"}',
        seq_start=1,
    )
    assert len(init_events) == 2
    assert init_events[0].event_type == "thread_started"
    assert init_events[0].payload["thread_id"] == "sid-1"
    assert init_events[1].event_type == "turn_started"

    msg_events = adapter.normalize_event(
        '{"type":"message","role":"assistant","content":"hello"}',
        seq_start=3,
    )
    assert len(msg_events) == 1
    assert msg_events[0].event_type == "assistant_message"
    assert msg_events[0].payload["text"] == "hello"

    done_events = adapter.normalize_event(
        '{"type":"result","status":"success"}',
        seq_start=4,
    )
    assert len(done_events) == 1
    assert done_events[0].event_type == "turn_completed"
    assert done_events[0].payload["status"] == "success"


def test_normalize_invalid_gemini_json_returns_error() -> None:
    adapter = GeminiAdapter()
    events = adapter.normalize_event("not-json", seq_start=7)
    assert len(events) == 1
    assert events[0].event_type == "error"
