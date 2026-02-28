from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from telegram_bot_new.adapters.base import AdapterEvent
from telegram_bot_new.db.repository import LeasedRunJob
from telegram_bot_new.telegram.client import TelegramApiError
from telegram_bot_new.workers.run_worker import (
    _process_run_job,
    _augment_prompt_for_generation_request,
    _deliver_generated_artifacts,
    _looks_like_html_request,
    _looks_like_image_request,
)


class FakeTelegramClient:
    def __init__(self, *, fail_photo: bool = False) -> None:
        self.fail_photo = fail_photo
        self.photos: list[tuple[int, str, str | None]] = []
        self.documents: list[tuple[int, str, str | None]] = []

    async def send_photo(self, *, chat_id: int, file_path: str, caption: str | None = None) -> None:
        if self.fail_photo:
            raise TelegramApiError("sendPhoto failed")
        self.photos.append((chat_id, file_path, caption))

    async def send_document(self, *, chat_id: int, file_path: str, caption: str | None = None) -> None:
        self.documents.append((chat_id, file_path, caption))


class FakeStreamer:
    def __init__(self) -> None:
        self.delivery_errors: list[str] = []

    async def append_delivery_error(self, *, turn_id: str, chat_id: int, message: str) -> None:
        self.delivery_errors.append(f"{turn_id}:{chat_id}:{message}")


@pytest.mark.asyncio
async def test_deliver_generated_artifacts_sends_photo_and_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "flower.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    html = tmp_path / "landing.html"
    html.write_text("<html><body>landing</body></html>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    client = FakeTelegramClient()
    streamer = FakeStreamer()
    sent_registry: dict[str, set[str]] = {}

    await _deliver_generated_artifacts(
        bot_id="bot-1",
        chat_id=1001,
        turn_id="turn-1",
        user_text="show me results",
        assistant_text="![img](./flower.png)\n[landing](./landing.html)",
        run_started_epoch=time.time(),
        telegram_client=client,
        streamer=streamer,
        sent_registry=sent_registry,
    )

    assert len(client.photos) == 1
    assert Path(client.photos[0][1]).name == "flower.png"
    assert len(client.documents) == 1
    assert Path(client.documents[0][1]).name == "landing.html"
    assert streamer.delivery_errors == []


@pytest.mark.asyncio
async def test_deliver_generated_artifacts_dedupe_allows_updated_same_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "flower.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nv1")
    monkeypatch.chdir(tmp_path)

    client = FakeTelegramClient()
    streamer = FakeStreamer()
    sent_registry: dict[str, set[str]] = {}

    kwargs = dict(
        bot_id="bot-1",
        chat_id=1001,
        turn_id="turn-dedupe",
        user_text="show image",
        assistant_text="![img](./flower.png)",
        run_started_epoch=time.time(),
        telegram_client=client,
        streamer=streamer,
        sent_registry=sent_registry,
    )
    await _deliver_generated_artifacts(**kwargs)
    await _deliver_generated_artifacts(**kwargs)
    assert len(client.photos) == 1

    image.write_bytes(b"\x89PNG\r\n\x1a\nv2")
    await _deliver_generated_artifacts(**kwargs)
    assert len(client.photos) == 2
    assert streamer.delivery_errors == []


@pytest.mark.asyncio
async def test_deliver_generated_artifacts_falls_back_to_send_document_when_photo_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "flower.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.chdir(tmp_path)

    client = FakeTelegramClient(fail_photo=True)
    streamer = FakeStreamer()

    await _deliver_generated_artifacts(
        bot_id="bot-1",
        chat_id=1001,
        turn_id="turn-2",
        user_text="show image",
        assistant_text="![img](./flower.png)",
        run_started_epoch=time.time(),
        telegram_client=client,
        streamer=streamer,
        sent_registry={},
    )

    assert client.photos == []
    assert len(client.documents) == 1
    assert Path(client.documents[0][1]).name == "flower.png"
    assert streamer.delivery_errors == []


@pytest.mark.asyncio
async def test_deliver_generated_artifacts_uses_recent_file_fallback_for_korean_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "recent.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.chdir(tmp_path)

    client = FakeTelegramClient()
    streamer = FakeStreamer()

    def fake_find_recent_files(*, since_epoch: float, suffixes: set[str], limit: int = 3) -> list[Path]:
        return [image]

    monkeypatch.setattr("telegram_bot_new.workers.run_worker._find_recent_files", fake_find_recent_files)

    await _deliver_generated_artifacts(
        bot_id="bot-1",
        chat_id=1001,
        turn_id="turn-3",
        user_text="\uaf43 \uc774\ubbf8\uc9c0 \ub9cc\ub4e4\uace0 \ud604\uc7ac \uc774\ubbf8\uc9c0 \ucc3d\uc5d0 \ubcf4\uc5ec\uc918",
        assistant_text="",
        run_started_epoch=time.time(),
        telegram_client=client,
        streamer=streamer,
        sent_registry={},
    )

    assert len(client.photos) == 1
    assert Path(client.photos[0][1]).name == "recent.png"
    assert streamer.delivery_errors == []


def test_generation_request_detection_and_prompt_contract() -> None:
    image_text = "\uaf43 \uc774\ubbf8\uc9c0 \ub9cc\ub4e4\uc5b4\uc918"
    html_text = "\ub79c\ub529 \ud398\uc774\uc9c0 html css\ub85c \ub9cc\ub4e4\uc5b4\uc918"

    assert _looks_like_image_request(image_text)
    assert _looks_like_html_request(html_text)

    combined = _augment_prompt_for_generation_request(f"{image_text}\n{html_text}")
    assert "Image Delivery Contract" in combined
    assert "HTML Delivery Contract" in combined


class _AdapterForWorkerTest:
    async def run_new_turn(self, request):
        yield AdapterEvent(seq=1, ts="2026-01-01T00:00:00+00:00", event_type="thread_started", payload={"thread_id": "t-1"})
        yield AdapterEvent(
            seq=2,
            ts="2026-01-01T00:00:01+00:00",
            event_type="assistant_message",
            payload={"text": "ok"},
        )
        yield AdapterEvent(
            seq=3,
            ts="2026-01-01T00:00:02+00:00",
            event_type="turn_completed",
            payload={"status": "success"},
        )

    async def run_resume_turn(self, request):
        async for event in self.run_new_turn(request):
            yield event

    def extract_thread_id(self, event: AdapterEvent):
        return event.payload.get("thread_id")


class _SummaryServiceForWorkerTest:
    def build_recovery_preamble(self, summary: str) -> str:
        return ""

    def build_summary(self, summary_input) -> str:
        return "summary"


class _StreamerForWorkerTest:
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


class _RepositoryForWorkerTest:
    def __init__(self, *, existing_events: int = 0, fail_append: bool = False) -> None:
        self._existing_events = existing_events
        self._fail_append = fail_append
        self.appended_seqs: list[int] = []
        self.completed = False
        self.failed = False
        self.failed_error = ""

    async def get_turn(self, *, turn_id: str):
        return SimpleNamespace(turn_id=turn_id, session_id="session-1", user_text="hello", chat_id="1001")

    async def get_session_view(self, *, session_id: str):
        return SimpleNamespace(
            session_id=session_id,
            adapter_name="codex",
            rolling_summary_md="",
            adapter_thread_id=None,
        )

    async def mark_run_in_flight(self, *, job_id: str, turn_id: str, now: int) -> None:
        return None

    async def get_turn_events_count(self, *, turn_id: str) -> int:
        return self._existing_events

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
        if self._fail_append:
            raise RuntimeError("append failed")
        self.appended_seqs.append(seq)

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


@pytest.mark.asyncio
async def test_process_run_job_continues_seq_after_existing_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _AdapterForWorkerTest())
    repo = _RepositoryForWorkerTest(existing_events=5)
    streamer = _StreamerForWorkerTest()

    await _process_run_job(
        job=LeasedRunJob(id="job-1", turn_id="turn-1", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryServiceForWorkerTest(),
        default_models_by_provider={"codex": None, "gemini": None, "claude": None},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.appended_seqs
    assert repo.appended_seqs[0] == 6
    assert repo.completed is True
    assert "turn-1" in streamer.closed_turns


@pytest.mark.asyncio
async def test_process_run_job_closes_stream_when_append_event_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("telegram_bot_new.workers.run_worker.get_adapter", lambda _name: _AdapterForWorkerTest())
    repo = _RepositoryForWorkerTest(existing_events=0, fail_append=True)
    streamer = _StreamerForWorkerTest()

    await _process_run_job(
        job=LeasedRunJob(id="job-2", turn_id="turn-2", chat_id="1001"),
        bot_id="bot-1",
        repository=repo,
        telegram_client=_TelegramClientNoop(),
        streamer=streamer,
        summary_service=_SummaryServiceForWorkerTest(),
        default_models_by_provider={"codex": None, "gemini": None, "claude": None},
        default_sandbox="workspace-write",
        lease_ms=30_000,
        sent_artifacts_by_chat={},
    )

    assert repo.failed is True
    assert "turn-2" in streamer.closed_turns
