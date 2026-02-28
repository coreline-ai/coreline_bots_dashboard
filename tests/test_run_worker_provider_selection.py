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
    def __init__(self, *, adapter_name: str) -> None:
        self.adapter_name = adapter_name
        self.completed = False
        self.failed = False
        self.failed_error = ""
        self.appended_events: list[tuple[str, str]] = []
        self.metrics: list[str] = []

    async def get_turn(self, *, turn_id: str):
        return SimpleNamespace(turn_id=turn_id, session_id="session-1", user_text="hello", chat_id="1001")

    async def get_session_view(self, *, session_id: str):
        return SimpleNamespace(
            session_id=session_id,
            adapter_name=self.adapter_name,
            rolling_summary_md="",
            adapter_thread_id=None,
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
        return False

    async def set_session_thread_id(self, *, session_id: str, thread_id: str | None, now: int) -> None:
        return None

    async def complete_run_job_and_turn(self, *, job_id: str, turn_id: str, assistant_text: str, now: int) -> None:
        self.completed = True

    async def fail_run_job_and_turn(self, *, job_id: str, turn_id: str, error_text: str, now: int) -> None:
        self.failed = True
        self.failed_error = error_text

    async def mark_run_job_cancelled(self, *, job_id: str, turn_id: str, now: int) -> None:
        return None

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
