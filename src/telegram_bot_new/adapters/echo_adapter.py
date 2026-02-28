from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import AdapterEvent, AdapterResumeRequest, AdapterRunRequest, CliAdapter, utc_now_iso


class EchoAdapter(CliAdapter):
    """Sample adapter for extension testing."""

    async def run_new_turn(self, request: AdapterRunRequest) -> AsyncIterator[AdapterEvent]:
        seq = 1
        yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="thread_started", payload={"thread_id": "echo-thread"})
        seq += 1
        yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="turn_started", payload={})
        seq += 1
        await asyncio.sleep(0.01)
        yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="assistant_message", payload={"text": f"echo: {request.prompt}"})
        seq += 1
        yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="turn_completed", payload={"status": "success"})

    async def run_resume_turn(self, request: AdapterResumeRequest) -> AsyncIterator[AdapterEvent]:
        seq = 1
        yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="thread_started", payload={"thread_id": request.thread_id})
        seq += 1
        yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="turn_started", payload={})
        seq += 1
        yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="assistant_message", payload={"text": f"echo-resume: {request.prompt}"})
        seq += 1
        yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="turn_completed", payload={"status": "success"})

    def normalize_event(self, raw_line: str, seq_start: int = 1) -> list[AdapterEvent]:
        return [AdapterEvent(seq=seq_start, ts=utc_now_iso(), event_type="reasoning", payload={"raw": raw_line})]

    def extract_thread_id(self, event: AdapterEvent) -> str | None:
        return event.payload.get("thread_id") if event.event_type == "thread_started" else None