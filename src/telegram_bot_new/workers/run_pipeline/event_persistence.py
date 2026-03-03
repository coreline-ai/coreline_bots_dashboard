from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from telegram_bot_new.adapters.base import AdapterEvent
from telegram_bot_new.db.repository import Repository
from telegram_bot_new.streaming.telegram_event_streamer import TelegramEventStreamer


@dataclass(slots=True)
class StreamOutcome:
    assistant_parts: list[str]
    command_notes: list[str]
    thread_id: str | None
    completion_status: str
    error_text: str | None
    error_stderr: str | None


async def consume_adapter_stream(
    *,
    stream: Any,
    adapter: Any,
    provider: str,
    turn: Any,
    bot_id: str,
    repository: Repository,
    streamer: TelegramEventStreamer,
    now_ms_fn,
    utc_now_iso_fn,
) -> StreamOutcome:
    # If this turn was partially processed before a worker restart/crash,
    # continue with the next sequence number to avoid unique key conflicts.
    seq = (await repository.get_turn_events_count(turn_id=turn.turn_id)) + 1
    assistant_parts: list[str] = []
    command_notes: list[str] = []
    thread_id: str | None = None
    completion_status = "success"
    error_text: str | None = None
    error_stderr: str | None = None

    async def _persist_and_stream_event(event: AdapterEvent) -> None:
        nonlocal seq
        await repository.append_cli_event(
            turn_id=turn.turn_id,
            bot_id=bot_id,
            seq=event.seq,
            event_type=event.event_type,
            payload_json=json.dumps({"ts": event.ts, "payload": event.payload}, ensure_ascii=False),
            now=now_ms_fn(),
        )
        try:
            await streamer.append_event(turn_id=turn.turn_id, chat_id=int(turn.chat_id), event=event)
        except Exception as stream_error:
            seq += 1
            await repository.append_cli_event(
                turn_id=turn.turn_id,
                bot_id=bot_id,
                seq=seq,
                event_type="delivery_error",
                payload_json=json.dumps({"message": str(stream_error)}),
                now=now_ms_fn(),
            )

    try:
        async for raw_event in stream:
            event = AdapterEvent(seq=seq, ts=raw_event.ts, event_type=raw_event.event_type, payload=raw_event.payload)
            await _persist_and_stream_event(event)

            if event.event_type == "assistant_message":
                text = event.payload.get("text")
                if isinstance(text, str) and text.strip():
                    assistant_parts.append(text)

            if event.event_type in ("command_started", "command_completed"):
                cmd = event.payload.get("command")
                if isinstance(cmd, str) and cmd:
                    command_notes.append(cmd)

            if event.event_type == "thread_started":
                candidate = adapter.extract_thread_id(event)
                if candidate:
                    thread_id = candidate

            if event.event_type == "turn_completed":
                status = event.payload.get("status")
                if isinstance(status, str):
                    completion_status = status

            if event.event_type == "error" and error_text is None:
                msg = event.payload.get("message")
                if isinstance(msg, str):
                    error_text = msg
                stderr = event.payload.get("stderr")
                if isinstance(stderr, str) and stderr.strip():
                    error_stderr = stderr

            seq += 1
    except FileNotFoundError:
        error_text = f"provider={provider} executable not found; install CLI or switch with /mode codex"
        completion_status = "error"
        await _persist_and_stream_event(
            AdapterEvent(
                seq=seq,
                ts=utc_now_iso_fn(),
                event_type="error",
                payload={"message": error_text},
            )
        )
        seq += 1
        await _persist_and_stream_event(
            AdapterEvent(
                seq=seq,
                ts=utc_now_iso_fn(),
                event_type="turn_completed",
                payload={"status": "error"},
            )
        )
    except Exception as stream_error:
        error_text = str(stream_error)
        completion_status = "error"
        await _persist_and_stream_event(
            AdapterEvent(
                seq=seq,
                ts=utc_now_iso_fn(),
                event_type="error",
                payload={"message": error_text},
            )
        )
        seq += 1
        await _persist_and_stream_event(
            AdapterEvent(
                seq=seq,
                ts=utc_now_iso_fn(),
                event_type="turn_completed",
                payload={"status": "error"},
            )
        )

    return StreamOutcome(
        assistant_parts=assistant_parts,
        command_notes=command_notes,
        thread_id=thread_id,
        completion_status=completion_status,
        error_text=error_text,
        error_stderr=error_stderr,
    )
