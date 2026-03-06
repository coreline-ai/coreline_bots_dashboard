from __future__ import annotations

import re
from pathlib import Path

import pytest

from telegram_bot_new.telegram.command_handlers.command_router import _handle_command


class _FakeClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_kwargs) -> int:
        self.messages.append((chat_id, text))
        return len(self.messages)


class _RouterHarness:
    def __init__(self) -> None:
        self._client = _FakeClient()
        self._youtube_search = object()
        self.calls: list[tuple[str, dict]] = []

    def _welcome_text(self) -> str:
        return "welcome"

    def _help_text(self) -> str:
        return "help"

    async def _handle_youtube_search(self, *, chat_id: int, query: str) -> None:
        self.calls.append(("youtube", {"chat_id": chat_id, "query": query}))

    async def _handle_new_command(self, *, chat_id: int, now_ms: int) -> None:
        self.calls.append(("new", {"chat_id": chat_id, "now_ms": now_ms}))

    async def _handle_status_command(self, *, chat_id: int) -> None:
        self.calls.append(("status", {"chat_id": chat_id}))

    async def _handle_reset_command(self, *, chat_id: int, now_ms: int) -> None:
        self.calls.append(("reset", {"chat_id": chat_id, "now_ms": now_ms}))

    async def _handle_summary_command(self, *, chat_id: int) -> None:
        self.calls.append(("summary", {"chat_id": chat_id}))

    async def _handle_mode_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
        self.calls.append(("mode", {"chat_id": chat_id, "arg": arg, "now_ms": now_ms}))

    async def _handle_model_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
        self.calls.append(("model", {"chat_id": chat_id, "arg": arg, "now_ms": now_ms}))

    async def _handle_project_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
        self.calls.append(("project", {"chat_id": chat_id, "arg": arg, "now_ms": now_ms}))

    async def _handle_skills_command(self, *, chat_id: int) -> None:
        self.calls.append(("skills", {"chat_id": chat_id}))

    async def _handle_skill_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
        self.calls.append(("skill", {"chat_id": chat_id, "arg": arg, "now_ms": now_ms}))

    async def _handle_unsafe_command(self, *, chat_id: int, arg: str, now_ms: int) -> None:
        self.calls.append(("unsafe", {"chat_id": chat_id, "arg": arg, "now_ms": now_ms}))

    async def _handle_providers_command(self, *, chat_id: int) -> None:
        self.calls.append(("providers", {"chat_id": chat_id}))

    async def _handle_stop_command(self, *, chat_id: int, now_ms: int) -> None:
        self.calls.append(("stop", {"chat_id": chat_id, "now_ms": now_ms}))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_call"),
    [
        ("/new", ("new", {"chat_id": 100, "now_ms": 77})),
        ("/status", ("status", {"chat_id": 100})),
        ("/reset", ("reset", {"chat_id": 100, "now_ms": 77})),
        ("/summary", ("summary", {"chat_id": 100})),
        ("/mode codex", ("mode", {"chat_id": 100, "arg": "codex", "now_ms": 77})),
        ("/model gpt-5.4", ("model", {"chat_id": 100, "arg": "gpt-5.4", "now_ms": 77})),
        ("/project /tmp/work", ("project", {"chat_id": 100, "arg": "/tmp/work", "now_ms": 77})),
        ("/skills", ("skills", {"chat_id": 100})),
        ("/skill remotion-best-practices", ("skill", {"chat_id": 100, "arg": "remotion-best-practices", "now_ms": 77})),
        ("/unsafe on 10", ("unsafe", {"chat_id": 100, "arg": "on 10", "now_ms": 77})),
        ("/providers", ("providers", {"chat_id": 100})),
        ("/stop", ("stop", {"chat_id": 100, "now_ms": 77})),
        ("/youtube python asyncio", ("youtube", {"chat_id": 100, "query": "python asyncio"})),
        ("/yt gemini cli", ("youtube", {"chat_id": 100, "query": "gemini cli"})),
    ],
)
async def test_router_dispatches_all_selectable_menu_commands(text: str, expected_call: tuple[str, dict]) -> None:
    harness = _RouterHarness()

    await _handle_command(harness, chat_id=100, text=text, now_ms=77)

    assert harness.calls == [expected_call]
    assert harness._client.messages == []


@pytest.mark.asyncio
async def test_router_handles_start_help_echo_commands() -> None:
    harness = _RouterHarness()

    await _handle_command(harness, chat_id=100, text="/start", now_ms=10)
    await _handle_command(harness, chat_id=100, text="/help", now_ms=11)
    await _handle_command(harness, chat_id=100, text="/echo hello", now_ms=12)
    await _handle_command(harness, chat_id=100, text="/echo", now_ms=13)

    assert harness.calls == []
    assert harness._client.messages == [
        (100, "welcome"),
        (100, "help"),
        (100, "hello"),
        (100, "(empty)"),
    ]


@pytest.mark.asyncio
async def test_router_handles_youtube_menu_validation_cases() -> None:
    harness = _RouterHarness()

    harness._youtube_search = None
    await _handle_command(harness, chat_id=100, text="/youtube query", now_ms=20)
    assert harness._client.messages[-1] == (100, "YouTube search is not enabled.")

    harness._youtube_search = object()
    await _handle_command(harness, chat_id=100, text="/yt", now_ms=21)
    assert harness._client.messages[-1] == (100, "Usage: /youtube <query>")


@pytest.mark.asyncio
async def test_router_handles_unknown_command() -> None:
    harness = _RouterHarness()

    await _handle_command(harness, chat_id=100, text="/unknown", now_ms=30)

    assert harness._client.messages[-1] == (100, "Unknown command: /unknown\n\nhelp")


def test_ui_command_catalog_is_in_sync_with_router_menu_commands() -> None:
    app_js = Path("src/telegram_bot_new/mock_messenger/web/app.js").read_text(encoding="utf-8")
    ui_commands = set(re.findall(r'\{\s*command:\s*"(/[^"]+)"', app_js))
    expected_commands = {
        "/start",
        "/help",
        "/new",
        "/status",
        "/reset",
        "/summary",
        "/mode",
        "/model",
        "/skills",
        "/skill",
        "/project",
        "/unsafe",
        "/providers",
        "/stop",
        "/youtube",
        "/yt",
        "/echo",
    }

    assert expected_commands.issubset(ui_commands)
    assert len(expected_commands) == 17
