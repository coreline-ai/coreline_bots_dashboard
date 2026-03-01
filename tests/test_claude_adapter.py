import pytest

from telegram_bot_new.adapters.base import AdapterResumeRequest, AdapterRunRequest
from telegram_bot_new.adapters.claude_adapter import ClaudeAdapter


@pytest.mark.asyncio
async def test_run_new_turn_builds_expected_claude_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_process(self: ClaudeAdapter, args: list[str], should_cancel, workdir=None):
        captured["args"] = args
        captured["workdir"] = workdir
        if False:
            yield

    monkeypatch.setattr(ClaudeAdapter, "_run_process", fake_run_process)

    adapter = ClaudeAdapter(claude_bin="claude")
    request = AdapterRunRequest(
        prompt="hello",
        model="claude-sonnet-4-5",
        preamble="memory",
    )

    events = [event async for event in adapter.run_new_turn(request)]

    assert events == []
    assert captured["args"] == [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--model",
        "claude-sonnet-4-5",
        "memory\n\n[User Message]\nhello",
    ]
    assert captured["workdir"] is None


@pytest.mark.asyncio
async def test_run_resume_turn_builds_expected_claude_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_process(self: ClaudeAdapter, args: list[str], should_cancel, workdir=None):
        captured["args"] = args
        captured["workdir"] = workdir
        if False:
            yield

    monkeypatch.setattr(ClaudeAdapter, "_run_process", fake_run_process)

    adapter = ClaudeAdapter(claude_bin="claude")
    request = AdapterResumeRequest(
        thread_id="c-session-1",
        prompt="continue",
        model="claude-sonnet-4-5",
        preamble="memory",
    )

    events = [event async for event in adapter.run_resume_turn(request)]

    assert events == []
    assert captured["args"] == [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "-r",
        "c-session-1",
        "--model",
        "claude-sonnet-4-5",
        "memory\n\n[User Message]\ncontinue",
    ]
    assert captured["workdir"] is None


def test_normalize_claude_events() -> None:
    adapter = ClaudeAdapter()

    init_events = adapter.normalize_event(
        '{"type":"system","subtype":"init","session_id":"sid-1"}',
        seq_start=1,
    )
    assert len(init_events) == 2
    assert init_events[0].event_type == "thread_started"
    assert init_events[0].payload["thread_id"] == "sid-1"
    assert init_events[1].event_type == "turn_started"

    msg_events = adapter.normalize_event(
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"hello"}]}}',
        seq_start=3,
    )
    assert len(msg_events) == 1
    assert msg_events[0].event_type == "assistant_message"
    assert msg_events[0].payload["text"] == "hello"

    done_events = adapter.normalize_event(
        '{"type":"result","subtype":"success","is_error":false}',
        seq_start=4,
    )
    assert len(done_events) == 1
    assert done_events[0].event_type == "turn_completed"
    assert done_events[0].payload["status"] == "success"


def test_normalize_invalid_claude_json_returns_error() -> None:
    adapter = ClaudeAdapter()
    events = adapter.normalize_event("not-json", seq_start=7)
    assert len(events) == 1
    assert events[0].event_type == "error"
