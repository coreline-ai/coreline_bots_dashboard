from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from telegram_bot_new.adapters.base import AdapterEvent
from telegram_bot_new.db.repository import LeasedRunJob
from telegram_bot_new.workers.run_worker import _process_run_job


class _CaptureAdapter:
    def __init__(self) -> None:
        self.last_request = None

    async def run_new_turn(self, request):
        self.last_request = request
        yield AdapterEvent(seq=1, ts="2026-01-01T00:00:00+00:00", event_type="thread_started", payload={"thread_id": "g-1"})
        yield AdapterEvent(seq=2, ts="2026-01-01T00:00:01+00:00", event_type="assistant_message", payload={"text": "ok"})
        yield AdapterEvent(seq=3, ts="2026-01-01T00:00:02+00:00", event_type="turn_completed", payload={"status": "success"})

    async def run_resume_turn(self, request):
        self.last_request = request
        yield AdapterEvent(seq=1, ts="2026-01-01T00:00:00+00:00", event_type="assistant_message", payload={"text": "resume"})
        yield AdapterEvent(seq=2, ts="2026-01-01T00:00:01+00:00", event_type="turn_completed", payload={"status": "success"})

    def extract_thread_id(self, event: AdapterEvent):
        return event.payload.get("thread_id") if event.event_type == "thread_started" else None


class _MissingBinAdapter:
    async def run_new_turn(self, request):
        if False:
            yield
        raise FileNotFoundError("missing binary")

    async def run_resume_turn(self, request):
        if False:
            yield
        raise FileNotFoundError("missing binary")

    def extract_thread_id(self, event: AdapterEvent):
        return None


class _WatchdogTimeoutAdapter:
    async def _emit_timeout(self):
        yield AdapterEvent(
            seq=1,
            ts="2026-01-01T00:00:00+00:00",
            event_type="error",
            payload={"message": "adapter stream timed out or cancelled"},
        )
        yield AdapterEvent(seq=2, ts="2026-01-01T00:00:01+00:00", event_type="turn_completed", payload={"status": "error"})

    async def run_new_turn(self, request):
        async for event in self._emit_timeout():
            yield event

    async def run_resume_turn(self, request):
        async for event in self._emit_timeout():
            yield event

    def extract_thread_id(self, event: AdapterEvent):
        return None


class _GeminiQuotaErrorAdapter:
    async def _emit_quota_error(self):
        yield AdapterEvent(
            seq=1,
            ts="2026-01-01T00:00:00+00:00",
            event_type="error",
            payload={
                "message": "api error: you have exhausted your capacity on this model",
                "stderr": "quota will reset after 00:00 UTC",
            },
        )
        yield AdapterEvent(seq=2, ts="2026-01-01T00:00:01+00:00", event_type="turn_completed", payload={"status": "error"})

    async def run_new_turn(self, request):
        async for event in self._emit_quota_error():
            yield event

    async def run_resume_turn(self, request):
        async for event in self._emit_quota_error():
            yield event

    def extract_thread_id(self, event: AdapterEvent):
        return None


class _GeminiHumanInputRequiredAdapter:
    async def _emit_human_input_required_error(self):
        yield AdapterEvent(
            seq=1,
            ts="2026-01-01T00:00:00+00:00",
            event_type="error",
            payload={
                "message": "Gemini requires human input: open browser and sign in via OAuth.",
                "stderr": "interactive confirmation required",
            },
        )
        yield AdapterEvent(seq=2, ts="2026-01-01T00:00:01+00:00", event_type="turn_completed", payload={"status": "error"})

    async def run_new_turn(self, request):
        async for event in self._emit_human_input_required_error():
            yield event

    async def run_resume_turn(self, request):
        async for event in self._emit_human_input_required_error():
            yield event

    def extract_thread_id(self, event: AdapterEvent):
        return None


class _CodexAccessLimitedAdapter:
    async def _emit_access_limited_error(self):
        yield AdapterEvent(
            seq=1,
            ts="2026-01-01T00:00:00+00:00",
            event_type="error",
            payload={
                "message": (
                    "This user's access to gpt-5.3-codex-premium-1p-codexswic-ev3 "
                    "has been temporarily limited for potentially suspicious activity "
                    "related to cybersecurity."
                ),
            },
        )
        yield AdapterEvent(seq=2, ts="2026-01-01T00:00:01+00:00", event_type="turn_completed", payload={"status": "error"})

    async def run_new_turn(self, request):
        async for event in self._emit_access_limited_error():
            yield event

    async def run_resume_turn(self, request):
        async for event in self._emit_access_limited_error():
            yield event

    def extract_thread_id(self, event: AdapterEvent):
        return None


class _CancelledAdapter:
    async def run_new_turn(self, request):
        should_cancel = await request.should_cancel()
        yield AdapterEvent(
            seq=1,
            ts="2026-01-01T00:00:00+00:00",
            event_type="turn_completed",
            payload={"status": "cancelled" if should_cancel else "success"},
        )

    async def run_resume_turn(self, request):
        async for event in self.run_new_turn(request):
            yield event

    def extract_thread_id(self, event: AdapterEvent):
        return None


class _SummaryService:
    def build_recovery_preamble(self, summary: str) -> str:
        return ""

    def build_summary(self, summary_input) -> str:
        return "summary"


class _Streamer:
    def __init__(self) -> None:
        self.closed_turns: list[str] = []

    async def append_event(self, *, turn_id: str, chat_id: int, event: AdapterEvent) -> None:
        return None

    async def close_turn(self, *, turn_id: str) -> None:
        self.closed_turns.append(turn_id)

    async def append_delivery_error(self, *, turn_id: str, chat_id: int, message: str) -> None:
        return None


class _TelegramClientNoop:
    async def send_photo(self, *, chat_id: int, file_path: str, caption: str | None = None) -> None:
        return None

    async def send_document(self, *, chat_id: int, file_path: str, caption: str | None = None) -> None:
        return None


class _Repository:
    def __init__(
        self,
        *,
        adapter_name: str,
        adapter_model: str | None = None,
        active_skill: str | None = None,
        project_root: str | None = None,
        unsafe_until: int | None = None,
        adapter_thread_id: str | None = None,
        user_text: str = "hello",
    ) -> None:
        self.adapter_name = adapter_name
        self.adapter_model = adapter_model
        self.active_skill = active_skill
        self.project_root = project_root
        self.unsafe_until = unsafe_until
        self.adapter_thread_id = adapter_thread_id
        self.user_text = user_text
        self.completed = False
        self.failed = False
        self.failed_error = ""
        self.cancelled_marked = False
        self.appended_events: list[tuple[str, str]] = []
        self.metrics: list[str] = []
        self.last_set_unsafe_until: int | None | object = object()
        self.thread_updates: list[str | None] = []
        self.set_model_calls: list[str] = []
        self.set_adapter_calls: list[str] = []
        self.turn_cancelled = False

    async def get_turn(self, *, turn_id: str):
        return SimpleNamespace(turn_id=turn_id, session_id="session-1", user_text=self.user_text, chat_id="1001")

    async def get_session_view(self, *, session_id: str):
        return SimpleNamespace(
            session_id=session_id,
            adapter_name=self.adapter_name,
            adapter_model=self.adapter_model,
            active_skill=self.active_skill,
            project_root=self.project_root,
            unsafe_until=self.unsafe_until,
            rolling_summary_md="",
            adapter_thread_id=self.adapter_thread_id,
        )

    async def mark_run_in_flight(self, *, job_id: str, turn_id: str, now: int) -> None:
        return None

    async def get_turn_events_count(self, *, turn_id: str) -> int:
        return 0

    async def append_cli_event(
        self,
        *,
        turn_id: str,
        bot_id: str,
        seq: int,
        event_type: str,
        payload_json: str,
        now: int,
    ) -> None:
        self.appended_events.append((event_type, payload_json))

    async def is_turn_cancelled(self, *, turn_id: str) -> bool:
        return self.turn_cancelled

    async def set_session_thread_id(self, *, session_id: str, thread_id: str | None, now: int) -> None:
        self.thread_updates.append(thread_id)
        self.adapter_thread_id = thread_id

    async def set_session_unsafe_until(self, *, session_id: str, unsafe_until: int | None, now: int) -> None:
        self.last_set_unsafe_until = unsafe_until
        self.unsafe_until = unsafe_until

    async def set_session_model(self, *, session_id: str, adapter_model: str | None, now: int) -> None:
        self.adapter_model = adapter_model
        self.set_model_calls.append(adapter_model or "default")

    async def set_session_adapter(
        self,
        *,
        session_id: str,
        adapter_name: str,
        adapter_model: str | None,
        now: int,
    ) -> None:
        self.adapter_name = adapter_name
        self.adapter_model = adapter_model
        self.set_adapter_calls.append(f"{adapter_name}:{adapter_model or 'default'}")

    async def complete_run_job_and_turn(self, *, job_id: str, turn_id: str, assistant_text: str, now: int) -> None:
        self.completed = True

    async def fail_run_job_and_turn(self, *, job_id: str, turn_id: str, error_text: str, now: int) -> None:
        self.failed = True
        self.failed_error = error_text

    async def mark_run_job_cancelled(self, *, job_id: str, turn_id: str, now: int) -> None:
        self.cancelled_marked = True

    async def upsert_session_summary(
        self,
        *,
        session_id: str,
        bot_id: str,
        turn_id: str,
        summary_md: str,
        now: int,
    ) -> None:
        return None

    async def promote_next_deferred_action(self, *, bot_id: str, chat_id: str, now: int):
        return None

    async def renew_run_job_lease(self, *, job_id: str, now: int, lease_duration_ms: int) -> None:
        return None

    async def increment_runtime_metric(self, *, bot_id: str, metric_key: str, now: int, delta: int = 1) -> None:
        self.metrics.append(metric_key)


@pytest.mark.asyncio
async def test_process_run_job_uses_provider_specific_model_and_codex_only_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _CaptureAdapter()
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: adapter)
    repo = _Repository(adapter_name="gemini")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-1", turn_id="turn-1", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert adapter.last_request is not None
    assert adapter.last_request.model == "gemini-2.5-pro"
    assert adapter.last_request.sandbox == ""
    assert repo.completed is True
    assert repo.failed is False


@pytest.mark.asyncio
async def test_process_run_job_reports_missing_provider_binary_with_standard_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _MissingBinAdapter())
    repo = _Repository(adapter_name="gemini")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-2", turn_id="turn-2", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.failed is True
    assert "provider=gemini executable not found" in repo.failed_error
    assert "provider_run_failed.gemini" in repo.metrics
    event_types = [event_type for event_type, _ in repo.appended_events]
    assert "error" in event_types
    assert "turn_completed" in event_types
    payloads = [json.loads(payload_json) for _, payload_json in repo.appended_events]
    assert any("provider=gemini executable not found" in (payload.get("payload", {}).get("message", "")) for payload in payloads)


@pytest.mark.asyncio
async def test_process_run_job_prefers_session_model_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _CaptureAdapter()
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: adapter)
    repo = _Repository(adapter_name="gemini", adapter_model="gemini-2.5-flash")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-3", turn_id="turn-3", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert adapter.last_request is not None
    assert adapter.last_request.model == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_process_run_job_uses_session_project_root_as_workdir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    adapter = _CaptureAdapter()
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: adapter)
    repo = _Repository(adapter_name="gemini", adapter_model="gemini-2.5-flash", project_root=str(tmp_path.resolve()))
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-4", turn_id="turn-4", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert adapter.last_request is not None
    assert adapter.last_request.workdir == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_process_run_job_enables_dangerous_sandbox_when_unsafe_active(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _CaptureAdapter()
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: adapter)
    repo = _Repository(adapter_name="codex", adapter_model="gpt-5", unsafe_until=9_999_999_999_999)
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-5", turn_id="turn-5", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert adapter.last_request is not None
    assert adapter.last_request.sandbox == "danger-full-access"


@pytest.mark.asyncio
async def test_process_run_job_clears_expired_unsafe_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _CaptureAdapter()
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: adapter)
    repo = _Repository(adapter_name="codex", adapter_model="gpt-5", unsafe_until=1)
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-6", turn_id="turn-6", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert adapter.last_request is not None
    assert adapter.last_request.sandbox == "workspace-write"
    assert repo.last_set_unsafe_until is None


@pytest.mark.asyncio
async def test_process_run_job_applies_auto_route_prefix_and_switches_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    gemini_adapter = _CaptureAdapter()
    codex_adapter = _CaptureAdapter()
    requested: list[str] = []

    def _adapter_factory(name: str):
        requested.append(name)
        if name == "codex":
            return codex_adapter
        return gemini_adapter

    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", _adapter_factory)
    repo = _Repository(adapter_name="gemini", adapter_model=None, user_text="@auto fix bug in code path")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-7", turn_id="turn-7", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.completed is True
    assert requested[0] == "codex"
    assert codex_adapter.last_request is not None
    assert codex_adapter.last_request.model == "gpt-5.3-codex"
    assert codex_adapter.last_request.prompt.startswith("fix bug in code path")


@pytest.mark.asyncio
async def test_process_run_job_injects_active_skill_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _CaptureAdapter()
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: adapter)
    monkeypatch.setattr(
        "telegram_bot_new.workers.run_worker.build_skill_instruction",
        lambda *, skill_id, prompt: "[skill] demo guidance" if skill_id == "demo-skill" else None,
    )
    repo = _Repository(adapter_name="gemini", active_skill="demo-skill", user_text="animate intro")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-8", turn_id="turn-8", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert adapter.last_request is not None
    assert "[Skill Guidance]" in (adapter.last_request.preamble or "")
    assert "demo guidance" in (adapter.last_request.preamble or "")


@pytest.mark.asyncio
async def test_process_run_job_injects_multiple_skills_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _CaptureAdapter()
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: adapter)
    monkeypatch.setattr(
        "telegram_bot_new.workers.run_worker.build_skill_instruction",
        lambda *, skill_id, prompt: "[skill] multi guidance" if skill_id == "demo-skill,audio-skill" else None,
    )
    repo = _Repository(adapter_name="gemini", active_skill="demo-skill,audio-skill", user_text="animate intro and mix audio")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-8b", turn_id="turn-8b", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert adapter.last_request is not None
    assert "[Skill Guidance]" in (adapter.last_request.preamble or "")
    assert "multi guidance" in (adapter.last_request.preamble or "")


@pytest.mark.asyncio
async def test_process_run_job_watchdog_timeout_auto_recovers_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _WatchdogTimeoutAdapter())
    repo = _Repository(adapter_name="gemini", adapter_thread_id="stale-thread-1")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-9", turn_id="turn-9", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.failed is True
    assert repo.thread_updates == [None]
    assert "provider_run_watchdog_timeout.gemini" in repo.metrics


@pytest.mark.asyncio
async def test_process_run_job_applies_gemini_quota_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _GeminiQuotaErrorAdapter())
    repo = _Repository(adapter_name="gemini", adapter_model="gemini-2.5-pro")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-10", turn_id="turn-10", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.failed is True
    assert repo.set_model_calls == ["gemini-2.5-flash"]
    assert "auto-switched model to gemini-2.5-flash" in repo.failed_error


@pytest.mark.asyncio
async def test_process_run_job_applies_gemini_human_input_provider_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _GeminiHumanInputRequiredAdapter())
    repo = _Repository(adapter_name="gemini", adapter_model="gemini-2.5-pro")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-10a", turn_id="turn-10a", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.failed is True
    assert repo.set_adapter_calls == ["codex:gpt-5"]
    assert "auto-switched provider to codex/gpt-5" in repo.failed_error


@pytest.mark.asyncio
async def test_process_run_job_applies_codex_access_limited_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _CodexAccessLimitedAdapter())
    repo = _Repository(adapter_name="codex", adapter_model="gpt-5.3-codex")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-10b", turn_id="turn-10b", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.failed is True
    assert repo.set_model_calls == ["gpt-5"]
    assert "auto-switched model to gpt-5" in repo.failed_error


@pytest.mark.asyncio
async def test_process_run_job_marks_cancelled_when_turn_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _CancelledAdapter())
    repo = _Repository(adapter_name="gemini")
    repo.turn_cancelled = True
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-11", turn_id="turn-11", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.cancelled_marked is True
    assert repo.completed is False
    assert repo.failed is False


@pytest.mark.asyncio
async def test_process_run_job_treats_deadline_timeout_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _CancelledAdapter())
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.RUN_TURN_TIMEOUT_SEC", 0)
    repo = _Repository(adapter_name="gemini")
    streamer = _Streamer()

    await _process_run_job(
        job=LeasedRunJob(id="job-12", turn_id="turn-12", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryService(),
        default_models_by_provider={"codex": "gpt-5.3-codex", "gemini": "gemini-2.5-pro", "claude": "claude-sonnet-4-5"},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.failed is True
    assert "turn timed out after 0s" in repo.failed_error
    assert "provider_run_watchdog_timeout.gemini" in repo.metrics
