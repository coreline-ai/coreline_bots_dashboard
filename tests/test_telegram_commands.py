from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from telegram_bot_new.db.repository import ActiveRunExistsError
from telegram_bot_new.services.action_token_service import ActionTokenPayload
from telegram_bot_new.telegram.commands import BotIdentity, TelegramCommandHandler


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.callbacks: list[tuple[str, str | None]] = []
        self.message_kwargs: list[dict] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> int:
        self.messages.append((chat_id, text))
        self.message_kwargs.append(kwargs)
        return len(self.messages)

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.callbacks.append((callback_query_id, text))


class FailingCallbackTelegramClient(FakeTelegramClient):
    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        raise RuntimeError("callback send failed")


@dataclass
class FakeSession:
    session_id: str


class FakeSessionService:
    def __init__(self, summary: str = "") -> None:
        self.summary = summary

    async def get_or_create(
        self,
        *,
        bot_id: str,
        chat_id: str,
        adapter_name: str,
        adapter_model: str | None,
        project_root: str | None = None,
        unsafe_until: int | None = None,
        now: int,
    ) -> FakeSession:
        return FakeSession(session_id="session-1")

    async def create_new(
        self,
        *,
        bot_id: str,
        chat_id: str,
        adapter_name: str,
        adapter_model: str | None,
        project_root: str | None = None,
        unsafe_until: int | None = None,
        now: int,
    ) -> FakeSession:
        return FakeSession(session_id="session-new")

    async def status(self, *, bot_id: str, chat_id: str):
        return None

    async def reset(self, *, session_id: str, now: int) -> None:
        return None

    async def get_summary(self, *, bot_id: str, chat_id: str) -> str:
        return self.summary


class FakeSessionServiceForMode:
    def __init__(self, *, adapter_name: str = "codex") -> None:
        self.session_id = "session-1"
        self.adapter_name = adapter_name
        self.adapter_model = "gpt-5" if adapter_name == "codex" else None
        self.project_root: str | None = None
        self.unsafe_until: int | None = None
        self.summary_preview = "summary"
        self.last_create_new_adapter: str | None = None
        self.last_create_new_model: str | None = None

    async def get_or_create(
        self,
        *,
        bot_id: str,
        chat_id: str,
        adapter_name: str,
        adapter_model: str | None,
        project_root: str | None = None,
        unsafe_until: int | None = None,
        now: int,
    ):
        self.adapter_name = adapter_name
        self.adapter_model = adapter_model
        self.project_root = project_root
        self.unsafe_until = unsafe_until
        return SimpleNamespace(session_id=self.session_id)

    async def create_new(
        self,
        *,
        bot_id: str,
        chat_id: str,
        adapter_name: str,
        adapter_model: str | None,
        project_root: str | None = None,
        unsafe_until: int | None = None,
        now: int,
    ):
        self.last_create_new_adapter = adapter_name
        self.last_create_new_model = adapter_model
        self.adapter_name = adapter_name
        self.adapter_model = adapter_model
        self.project_root = project_root
        self.unsafe_until = unsafe_until
        self.session_id = "session-new"
        return SimpleNamespace(session_id=self.session_id)

    async def status(self, *, bot_id: str, chat_id: str):
        return SimpleNamespace(
            session_id=self.session_id,
            adapter_name=self.adapter_name,
            adapter_model=self.adapter_model,
            project_root=self.project_root,
            unsafe_until=self.unsafe_until,
            adapter_thread_id=None,
            summary_preview=self.summary_preview,
        )

    async def reset(self, *, session_id: str, now: int) -> None:
        return None

    async def switch_adapter(
        self,
        *,
        session_id: str,
        adapter_name: str,
        adapter_model: str | None,
        now: int,
    ) -> None:
        self.adapter_name = adapter_name
        self.adapter_model = adapter_model

    async def set_model(self, *, session_id: str, adapter_model: str | None, now: int) -> None:
        self.adapter_model = adapter_model

    async def set_project_root(self, *, session_id: str, project_root: str | None, now: int) -> None:
        self.project_root = project_root

    async def set_unsafe_until(self, *, session_id: str, unsafe_until: int | None, now: int) -> None:
        self.unsafe_until = unsafe_until

    async def get_summary(self, *, bot_id: str, chat_id: str) -> str:
        return "summary"


class FakeRunService:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.enqueue_calls = 0
        self.button_enqueue_calls = 0
        self.deferred_calls = 0
        self.has_active = False

    async def enqueue_turn(self, **kwargs) -> str:
        self.enqueue_calls += 1
        if self.should_fail:
            raise ActiveRunExistsError("busy")
        return "turn-1"

    async def enqueue_button_turn(self, **kwargs) -> str:
        self.button_enqueue_calls += 1
        return "turn-button-1"

    async def enqueue_deferred_button_action(self, **kwargs) -> str:
        self.deferred_calls += 1
        return "deferred-1"

    async def has_active_run(self, **kwargs) -> bool:
        return self.has_active

    async def stop_active_turn(self, *, bot_id: str, chat_id: str, now: int):
        return "turn-1"


class FakeYoutubeSearchService:
    def __init__(self, *, result_url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ") -> None:
        self.result_url = result_url
        self.queries: list[str] = []

    async def search_first_video(self, query: str):
        self.queries.append(query)
        return type(
            "Result",
            (),
            {
                "video_id": "dQw4w9WgXcQ",
                "url": self.result_url,
                "title": "Test Video",
                "author_name": "Test Channel",
            },
        )()


class FakeActionTokenService:
    def __init__(self) -> None:
        self.issued: list[dict] = []
        self._next = 1
        self.consumed_payload = None

    async def issue(self, **kwargs) -> str:
        self.issued.append(kwargs)
        token = f"tok-{self._next}"
        self._next += 1
        return token

    async def consume(self, **kwargs):
        return self.consumed_payload


class RaisingActionTokenService(FakeActionTokenService):
    async def consume(self, **kwargs):
        raise RuntimeError("boom")


class FakePromptService:
    def __init__(self, prompt: str = "button prompt") -> None:
        self.prompt = prompt

    def build_summary_prompt(self, **kwargs) -> str:
        return self.prompt

    def build_regen_prompt(self, **kwargs) -> str:
        return self.prompt

    def build_next_prompt(self, **kwargs) -> str:
        return self.prompt


class FakeRepoTurn:
    def __init__(self, turn_id: str = "turn-1", user_text: str = "u", assistant_text: str = "a") -> None:
        self.turn_id = turn_id
        self.user_text = user_text
        self.assistant_text = assistant_text


class FakeRepoSession:
    def __init__(self, session_id: str = "session-1") -> None:
        self.session_id = session_id
        self.rolling_summary_md = "summary"


class FakeRepo:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, str]] = []
        self.audit_logs: list[dict] = []

    async def get_session_view(self, *, session_id: str):
        return FakeRepoSession(session_id=session_id)

    async def get_turn(self, *, turn_id: str):
        return FakeRepoTurn(turn_id=turn_id)

    async def get_latest_completed_turn_for_session(self, *, session_id: str):
        return FakeRepoTurn(turn_id="turn-latest", assistant_text="latest")

    async def increment_runtime_metric(self, *, bot_id: str, metric_key: str, now: int, delta: int = 1) -> None:
        self.metrics.append((bot_id, metric_key))

    async def append_audit_log(
        self,
        *,
        bot_id: str,
        chat_id: str | None,
        session_id: str | None,
        action: str,
        result: str,
        detail_json: str | None,
        now: int,
    ) -> None:
        self.audit_logs.append(
            {
                "bot_id": bot_id,
                "chat_id": chat_id,
                "session_id": session_id,
                "action": action,
                "result": result,
                "detail_json": detail_json,
                "now": now,
            }
        )


@pytest.mark.asyncio
async def test_owner_only_access_is_enforced() -> None:
    client = FakeTelegramClient()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 1,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 123},
            "message_id": 1,
            "text": "hello",
        },
    }

    await handler.handle_update_payload(payload, now_ms=1)

    assert client.messages
    assert "Access denied" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_plain_text_enqueues_turn() -> None:
    client = FakeTelegramClient()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 2,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 2,
            "text": "build this",
        },
    }

    await handler.handle_update_payload(payload, now_ms=2)

    assert client.messages
    assert "Queued turn: turn-1" in client.messages[-1][1]
    assert "agent=codex" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_plain_text_reports_active_run() -> None:
    client = FakeTelegramClient()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(should_fail=True),
    )

    payload = {
        "update_id": 3,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 3,
            "text": "next",
        },
    }

    await handler.handle_update_payload(payload, now_ms=3)

    assert client.messages
    assert "already active" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_youtube_command_returns_preview_url_without_enqueuing_turn() -> None:
    client = FakeTelegramClient()
    run_service = FakeRunService()
    youtube = FakeYoutubeSearchService()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=run_service,
        youtube_search=youtube,
    )

    payload = {
        "update_id": 4,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 4,
            "text": "/youtube python asyncio tutorial",
        },
    }

    await handler.handle_update_payload(payload, now_ms=4)

    assert run_service.enqueue_calls == 0
    assert youtube.queries == ["python asyncio tutorial"]
    assert client.messages
    assert client.messages[-1][1] == youtube.result_url


@pytest.mark.asyncio
async def test_youtube_natural_language_request_is_handled_directly() -> None:
    client = FakeTelegramClient()
    run_service = FakeRunService()
    youtube = FakeYoutubeSearchService()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=run_service,
        youtube_search=youtube,
    )

    payload = {
        "update_id": 5,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 5,
            "text": "python asyncio tutorial 유튜브 찾아줘",
        },
    }

    await handler.handle_update_payload(payload, now_ms=5)

    assert run_service.enqueue_calls == 0
    assert youtube.queries
    assert "python asyncio tutorial" in youtube.queries[0]
    assert "유튜브" not in youtube.queries[0]
    assert client.messages
    assert client.messages[-1][1] == youtube.result_url


@pytest.mark.asyncio
async def test_youtube_natural_language_typo_variant_is_handled_directly() -> None:
    client = FakeTelegramClient()
    run_service = FakeRunService()
    youtube = FakeYoutubeSearchService()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=run_service,
        youtube_search=youtube,
    )

    payload = {
        "update_id": 6,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 6,
            "text": "백종원 유투브 미리 보기 형식으로 보여줘",
        },
    }

    await handler.handle_update_payload(payload, now_ms=6)

    assert run_service.enqueue_calls == 0
    assert youtube.queries == ["백종원"]
    assert client.messages
    assert client.messages[-1][1] == youtube.result_url


@pytest.mark.asyncio
async def test_plain_text_message_includes_inline_action_keyboard_when_enabled() -> None:
    client = FakeTelegramClient()
    action_tokens = FakeActionTokenService()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(),
        action_token_service=action_tokens,
    )

    payload = {
        "update_id": 7,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 7,
            "text": "do work",
        },
    }

    await handler.handle_update_payload(payload, now_ms=7)

    assert client.messages
    assert "Queued turn" in client.messages[-1][1]
    kwargs = client.message_kwargs[-1]
    reply_markup = kwargs.get("reply_markup")
    assert isinstance(reply_markup, dict)
    keyboard = reply_markup.get("inline_keyboard")
    assert isinstance(keyboard, list)
    assert len(action_tokens.issued) == 4


@pytest.mark.asyncio
async def test_callback_summary_enqueues_button_turn_when_idle() -> None:
    client = FakeTelegramClient()
    run_service = FakeRunService()
    action_tokens = FakeActionTokenService()
    action_tokens.consumed_payload = ActionTokenPayload(
        action_type="summary",
        run_source="codex_cli",
        chat_id="100",
        session_id="session-1",
        origin_turn_id="turn-1",
    )
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=run_service,
        repository=FakeRepo(),
        action_token_service=action_tokens,
        button_prompt_service=FakePromptService(prompt="summary prompt"),
    )

    payload = {
        "update_id": 8,
        "callback_query": {
            "id": "cb-1",
            "data": "act:tok-1",
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 8},
        },
    }
    await handler.handle_update_payload(payload, now_ms=8)

    assert run_service.button_enqueue_calls == 1
    assert run_service.deferred_calls == 0
    assert client.callbacks[-1][1] == "Started"


@pytest.mark.asyncio
async def test_callback_summary_queues_deferred_when_active_run_exists() -> None:
    client = FakeTelegramClient()
    run_service = FakeRunService()
    run_service.has_active = True
    action_tokens = FakeActionTokenService()
    action_tokens.consumed_payload = ActionTokenPayload(
        action_type="summary",
        run_source="codex_cli",
        chat_id="100",
        session_id="session-1",
        origin_turn_id="turn-1",
    )
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=run_service,
        repository=FakeRepo(),
        action_token_service=action_tokens,
        button_prompt_service=FakePromptService(prompt="summary prompt"),
    )

    payload = {
        "update_id": 9,
        "callback_query": {
            "id": "cb-2",
            "data": "act:tok-2",
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 9},
        },
    }
    await handler.handle_update_payload(payload, now_ms=9)

    assert run_service.button_enqueue_calls == 0
    assert run_service.deferred_calls == 1
    assert client.callbacks[-1][1] == "Queued after current run"


@pytest.mark.asyncio
async def test_callback_stop_token_uses_direct_cancel_flow() -> None:
    client = FakeTelegramClient()
    run_service = FakeRunService()
    action_tokens = FakeActionTokenService()
    action_tokens.consumed_payload = ActionTokenPayload(
        action_type="stop",
        run_source="direct_cancel",
        chat_id="100",
        session_id="session-1",
        origin_turn_id="turn-1",
    )
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=run_service,
        action_token_service=action_tokens,
    )

    payload = {
        "update_id": 10,
        "callback_query": {
            "id": "cb-3",
            "data": "act:tok-3",
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 10},
        },
    }
    await handler.handle_update_payload(payload, now_ms=10)

    assert client.callbacks[-1][1] == "Stopping..."


@pytest.mark.asyncio
async def test_callback_without_data_is_acknowledged_as_unsupported() -> None:
    client = FakeTelegramClient()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 11,
        "callback_query": {
            "id": "cb-missing",
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 11},
        },
    }

    await handler.handle_update_payload(payload, now_ms=11)

    assert client.callbacks[-1] == ("cb-missing", "Unsupported action")


@pytest.mark.asyncio
async def test_callback_exception_still_acknowledges_query() -> None:
    client = FakeTelegramClient()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(),
        action_token_service=RaisingActionTokenService(),
    )

    payload = {
        "update_id": 12,
        "callback_query": {
            "id": "cb-fail",
            "data": "act:tok-fail",
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 12},
        },
    }

    with pytest.raises(RuntimeError, match="boom"):
        await handler.handle_update_payload(payload, now_ms=12)

    assert client.callbacks[-1] == ("cb-fail", "Action failed")


@pytest.mark.asyncio
async def test_callback_with_expired_token_is_acknowledged() -> None:
    client = FakeTelegramClient()
    action_tokens = FakeActionTokenService()
    action_tokens.consumed_payload = None
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(),
        action_token_service=action_tokens,
    )

    payload = {
        "update_id": 13,
        "callback_query": {
            "id": "cb-expired",
            "data": "act:tok-expired",
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 13},
        },
    }

    await handler.handle_update_payload(payload, now_ms=13)

    assert client.callbacks[-1] == ("cb-expired", "Action expired or already used")


@pytest.mark.asyncio
async def test_callback_with_unknown_action_type_is_acknowledged() -> None:
    client = FakeTelegramClient()
    action_tokens = FakeActionTokenService()
    action_tokens.consumed_payload = ActionTokenPayload(
        action_type="unknown_action",
        run_source="codex_cli",
        chat_id="100",
        session_id="session-1",
        origin_turn_id="turn-1",
    )
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(),
        action_token_service=action_tokens,
    )

    payload = {
        "update_id": 14,
        "callback_query": {
            "id": "cb-unknown",
            "data": "act:tok-unknown",
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 14},
        },
    }

    await handler.handle_update_payload(payload, now_ms=14)

    assert client.callbacks[-1] == ("cb-unknown", "Unknown action")


@pytest.mark.asyncio
async def test_callback_ack_increments_metric_when_repository_available() -> None:
    client = FakeTelegramClient()
    run_service = FakeRunService()
    action_tokens = FakeActionTokenService()
    action_tokens.consumed_payload = ActionTokenPayload(
        action_type="summary",
        run_source="codex_cli",
        chat_id="100",
        session_id="session-1",
        origin_turn_id="turn-1",
    )
    repo = FakeRepo()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=run_service,
        repository=repo,
        action_token_service=action_tokens,
        button_prompt_service=FakePromptService(prompt="summary prompt"),
    )

    payload = {
        "update_id": 15,
        "callback_query": {
            "id": "cb-metric",
            "data": "act:tok-metric",
            "from": {"id": 999},
            "message": {"chat": {"id": 100}, "message_id": 15},
        },
    }
    await handler.handle_update_payload(payload, now_ms=15)

    assert ("b1", "callback_ack_success") in repo.metrics


@pytest.mark.asyncio
async def test_callback_ack_failure_increments_failed_metric() -> None:
    client = FailingCallbackTelegramClient()
    repo = FakeRepo()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=FakeSessionService(),
        run_service=FakeRunService(),
        repository=repo,
    )

    payload = {
        "update_id": 16,
        "callback_query": {
            "id": "cb-denied",
            "data": "act:tok-denied",
            "from": {"id": 123},
            "message": {"chat": {"id": 100}, "message_id": 16},
        },
    }
    await handler.handle_update_payload(payload, now_ms=16)

    assert ("b1", "callback_ack_failed") in repo.metrics


@pytest.mark.asyncio
async def test_mode_without_argument_shows_current_adapter_and_usage() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id="b1",
            bot_name="Bot",
            adapter="codex",
            owner_user_id=999,
            default_models={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "sonnet"},
        ),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 17,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 17, "text": "/mode"},
    }
    await handler.handle_update_payload(payload, now_ms=17)

    assert "adapter=codex" in client.messages[-1][1]
    assert "usage: /mode" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_status_uses_session_model_when_present() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="gemini")
    session_service.adapter_model = "gemini-2.5-flash"
    handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id="b1",
            bot_name="Bot",
            adapter="gemini",
            owner_user_id=999,
            default_models={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        ),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 170,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 170, "text": "/status"},
    }
    await handler.handle_update_payload(payload, now_ms=170)

    text = client.messages[-1][1]
    assert "adapter=gemini" in text
    assert "model=gemini-2.5-flash" in text
    assert "project=default" in text
    assert "unsafe_until=off" in text


@pytest.mark.asyncio
async def test_project_without_argument_shows_current_and_usage() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="gemini")
    session_service.project_root = "/tmp/project-a"
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="gemini", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 171,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 171, "text": "/project"},
    }
    await handler.handle_update_payload(payload, now_ms=171)

    text = client.messages[-1][1]
    assert "project=/tmp/project-a" in text
    assert "usage: /project" in text


@pytest.mark.asyncio
async def test_project_updates_session_workdir(tmp_path) -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 172,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 172,
            "text": f"/project {tmp_path}",
        },
    }
    await handler.handle_update_payload(payload, now_ms=172)

    assert session_service.project_root == str(tmp_path.resolve())
    assert "project updated: default ->" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_project_switch_is_blocked_when_run_is_active(tmp_path) -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    run_service = FakeRunService()
    run_service.has_active = True
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=run_service,
    )

    payload = {
        "update_id": 173,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 173,
            "text": f"/project {tmp_path}",
        },
    }
    await handler.handle_update_payload(payload, now_ms=173)

    assert "Use /stop first" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_unsafe_without_argument_shows_current_and_usage() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    session_service.unsafe_until = 12345
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 174,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 174, "text": "/unsafe"},
    }
    await handler.handle_update_payload(payload, now_ms=174)

    text = client.messages[-1][1]
    assert "unsafe_until=12345" in text
    assert "usage: /unsafe on" in text


@pytest.mark.asyncio
async def test_unsafe_updates_session_with_ttl() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 175,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 175, "text": "/unsafe on 15"},
    }
    await handler.handle_update_payload(payload, now_ms=1_000)

    assert session_service.unsafe_until == 1_000 + (15 * 60 * 1000)
    assert "unsafe updated: off ->" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_unsafe_switch_is_blocked_when_run_is_active() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    run_service = FakeRunService()
    run_service.has_active = True
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=run_service,
    )

    payload = {
        "update_id": 176,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 176, "text": "/unsafe on"},
    }
    await handler.handle_update_payload(payload, now_ms=176)

    assert "Use /stop first" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_project_command_appends_audit_log(tmp_path) -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    repo = FakeRepo()
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
        repository=repo,
    )

    payload = {
        "update_id": 177,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 999},
            "message_id": 177,
            "text": f"/project {tmp_path}",
        },
    }
    await handler.handle_update_payload(payload, now_ms=177)

    assert repo.audit_logs
    assert repo.audit_logs[-1]["action"] == "session.set_project"
    assert repo.audit_logs[-1]["result"] == "success"


@pytest.mark.asyncio
async def test_mode_switches_provider_and_increments_metric() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    repo = FakeRepo()
    handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id="b1",
            bot_name="Bot",
            adapter="codex",
            owner_user_id=999,
            default_models={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "sonnet"},
        ),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
        repository=repo,
    )

    payload = {
        "update_id": 18,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 18, "text": "/mode gemini"},
    }
    await handler.handle_update_payload(payload, now_ms=18)

    assert session_service.adapter_name == "gemini"
    assert session_service.adapter_model == "gemini-2.5-pro"
    assert "mode switched: codex -> gemini" in client.messages[-1][1]
    assert ("b1", "provider_switch_total.gemini") in repo.metrics


@pytest.mark.asyncio
async def test_mode_switch_is_blocked_when_run_is_active() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    run_service = FakeRunService()
    run_service.has_active = True
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=run_service,
    )

    payload = {
        "update_id": 19,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 19, "text": "/mode claude"},
    }
    await handler.handle_update_payload(payload, now_ms=19)

    assert session_service.adapter_name == "codex"
    assert "Use /stop first" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_model_without_argument_shows_current_and_available_models() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="gemini")
    session_service.adapter_model = "gemini-2.5-pro"
    handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id="b1",
            bot_name="Bot",
            adapter="gemini",
            owner_user_id=999,
            default_models={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        ),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 31,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 31, "text": "/model"},
    }
    await handler.handle_update_payload(payload, now_ms=31)

    text = client.messages[-1][1]
    assert "adapter=gemini" in text
    assert "model=gemini-2.5-pro" in text
    assert "available_models=gemini-2.5-pro, gemini-2.5-flash" in text


@pytest.mark.asyncio
async def test_model_updates_session_model() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="gemini")
    session_service.adapter_model = "gemini-2.5-pro"
    handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id="b1",
            bot_name="Bot",
            adapter="gemini",
            owner_user_id=999,
            default_models={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        ),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 32,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 32, "text": "/model gemini-2.5-flash"},
    }
    await handler.handle_update_payload(payload, now_ms=32)

    assert session_service.adapter_model == "gemini-2.5-flash"
    assert "model updated: gemini-2.5-pro -> gemini-2.5-flash" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_model_rejects_unsupported_model() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    session_service.adapter_model = "gpt-5"
    handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id="b1",
            bot_name="Bot",
            adapter="codex",
            owner_user_id=999,
            default_models={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        ),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 33,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 33, "text": "/model gemini-2.5-pro"},
    }
    await handler.handle_update_payload(payload, now_ms=33)

    assert "Unsupported model for codex" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_model_switch_is_blocked_when_run_is_active() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="claude")
    run_service = FakeRunService()
    run_service.has_active = True
    handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id="b1",
            bot_name="Bot",
            adapter="claude",
            owner_user_id=999,
            default_models={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        ),
        client=client,
        session_service=session_service,
        run_service=run_service,
    )

    payload = {
        "update_id": 34,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 34, "text": "/model claude-sonnet-4-5"},
    }
    await handler.handle_update_payload(payload, now_ms=34)

    assert "Use /stop first" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_mode_rejects_unsupported_provider() -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    handler = TelegramCommandHandler(
        bot=BotIdentity(bot_id="b1", bot_name="Bot", adapter="codex", owner_user_id=999),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    payload = {
        "update_id": 20,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 20, "text": "/mode unknown"},
    }
    await handler.handle_update_payload(payload, now_ms=20)

    assert "Unsupported provider" in client.messages[-1][1]


@pytest.mark.asyncio
async def test_providers_lists_installation_and_default_models(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTelegramClient()
    session_service = FakeSessionServiceForMode(adapter_name="codex")
    handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id="b1",
            bot_name="Bot",
            adapter="codex",
            owner_user_id=999,
            default_models={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "sonnet"},
        ),
        client=client,
        session_service=session_service,
        run_service=FakeRunService(),
    )

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name != "claude" else None

    monkeypatch.setattr("telegram_bot_new.telegram.commands.shutil.which", fake_which)

    payload = {
        "update_id": 21,
        "message": {"chat": {"id": 100}, "from": {"id": 999}, "message_id": 21, "text": "/providers"},
    }
    await handler.handle_update_payload(payload, now_ms=21)

    text = client.messages[-1][1]
    assert "codex: installed=yes, model=gpt-5" in text
    assert "gemini: installed=yes, model=gemini-2.5-pro" in text
    assert "claude: installed=no, model=sonnet" in text
