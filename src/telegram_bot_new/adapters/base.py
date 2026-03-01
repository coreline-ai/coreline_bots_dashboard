from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Protocol


AdapterEventType = Literal[
    "thread_started",
    "turn_started",
    "reasoning",
    "command_started",
    "command_completed",
    "assistant_message",
    "turn_completed",
    "error",
    "delivery_error",
]


@dataclass
class AdapterEvent:
    seq: int
    ts: str
    event_type: AdapterEventType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterRunRequest:
    prompt: str
    model: str | None = None
    sandbox: str = "workspace-write"
    workdir: str | None = None
    preamble: str | None = None
    should_cancel: Callable[[], Awaitable[bool]] | None = None


@dataclass
class AdapterResumeRequest(AdapterRunRequest):
    thread_id: str = ""


class CliAdapter(Protocol):
    async def run_new_turn(self, request: AdapterRunRequest) -> AsyncIterator[AdapterEvent]:
        ...

    async def run_resume_turn(self, request: AdapterResumeRequest) -> AsyncIterator[AdapterEvent]:
        ...

    def normalize_event(self, raw_line: str, seq_start: int = 1) -> list[AdapterEvent]:
        ...

    def extract_thread_id(self, event: AdapterEvent) -> str | None:
        ...


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
