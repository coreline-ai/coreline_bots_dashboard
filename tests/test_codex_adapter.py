import pytest

from telegram_bot_new.adapters.base import AdapterResumeRequest, AdapterRunRequest
from telegram_bot_new.adapters.codex_adapter import CodexAdapter


@pytest.mark.asyncio
async def test_run_new_turn_builds_expected_codex_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    async def fake_run_process(self: CodexAdapter, args: list[str], should_cancel):
        captured["args"] = args
        if False:
            yield

    monkeypatch.setattr(CodexAdapter, "_run_process", fake_run_process)

    adapter = CodexAdapter(codex_bin="codex")
    request = AdapterRunRequest(
        prompt="hello",
        model="gpt-5",
        sandbox="danger-full-access",
        preamble="memory",
    )

    events = [event async for event in adapter.run_new_turn(request)]

    assert events == []
    assert captured["args"] == [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-m",
        "gpt-5",
        "-s",
        "danger-full-access",
        "memory\n\n[User Message]\nhello",
    ]


@pytest.mark.asyncio
async def test_run_resume_turn_builds_expected_codex_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    async def fake_run_process(self: CodexAdapter, args: list[str], should_cancel):
        captured["args"] = args
        if False:
            yield

    monkeypatch.setattr(CodexAdapter, "_run_process", fake_run_process)

    adapter = CodexAdapter(codex_bin="codex")
    request = AdapterResumeRequest(
        thread_id="thread-1",
        prompt="continue",
        model="gpt-5",
        sandbox="danger-full-access",
        preamble="memory",
    )

    events = [event async for event in adapter.run_resume_turn(request)]

    assert events == []
    assert captured["args"] == [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-m",
        "gpt-5",
        "-s",
        "danger-full-access",
        "resume",
        "thread-1",
        "memory\n\n[User Message]\ncontinue",
    ]


def test_normalize_codex_events() -> None:
    adapter = CodexAdapter()

    thread_events = adapter.normalize_event('{"type":"thread.started","thread_id":"t-1"}', seq_start=3)
    assert len(thread_events) == 1
    assert thread_events[0].seq == 3
    assert thread_events[0].event_type == "thread_started"
    assert thread_events[0].payload["thread_id"] == "t-1"

    cmd_start = adapter.normalize_event(
        '{"type":"item.started","item":{"type":"command_execution","command":"ls"}}',
        seq_start=4,
    )
    assert cmd_start[0].event_type == "command_started"
    assert cmd_start[0].payload["command"] == "ls"

    cmd_done = adapter.normalize_event(
        '{"type":"item.completed","item":{"type":"command_execution","command":"ls","exit_code":0}}',
        seq_start=5,
    )
    assert cmd_done[0].event_type == "command_completed"
    assert cmd_done[0].payload["exit_code"] == 0

    done = adapter.normalize_event('{"type":"turn.completed","usage":{"in":1}}', seq_start=6)
    assert done[0].event_type == "turn_completed"


def test_normalize_invalid_json_returns_error() -> None:
    adapter = CodexAdapter()

    events = adapter.normalize_event("not-json", seq_start=7)

    assert len(events) == 1
    assert events[0].seq == 7
    assert events[0].event_type == "error"


def test_adapter_run_request_default_sandbox_is_workspace_write() -> None:
    request = AdapterRunRequest(prompt="hello")
    assert request.sandbox == "workspace-write"
