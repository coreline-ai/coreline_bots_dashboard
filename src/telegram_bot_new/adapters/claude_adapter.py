from __future__ import annotations

import asyncio
import contextlib
import json
from asyncio.subprocess import Process
from typing import Any, AsyncIterator

from .base import AdapterEvent, AdapterResumeRequest, AdapterRunRequest, CliAdapter, utc_now_iso


class ClaudeAdapter(CliAdapter):
    def __init__(self, claude_bin: str = "claude") -> None:
        self._claude_bin = claude_bin

    async def run_new_turn(self, request: AdapterRunRequest) -> AsyncIterator[AdapterEvent]:
        prompt = self._compose_prompt(request.preamble, request.prompt)
        args = [self._claude_bin, "-p", "--verbose", "--output-format", "stream-json"]
        if request.model:
            args.extend(["--model", request.model])
        args.append(prompt)

        async for event in self._run_process(args, request.should_cancel, request.workdir):
            yield event

    async def run_resume_turn(self, request: AdapterResumeRequest) -> AsyncIterator[AdapterEvent]:
        prompt = self._compose_prompt(request.preamble, request.prompt)
        args = [self._claude_bin, "-p", "--verbose", "--output-format", "stream-json", "-r", request.thread_id]
        if request.model:
            args.extend(["--model", request.model])
        args.append(prompt)

        async for event in self._run_process(args, request.should_cancel, request.workdir):
            yield event

    def normalize_event(self, raw_line: str, seq_start: int = 1) -> list[AdapterEvent]:
        line = raw_line.strip()
        if not line:
            return []

        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return [
                AdapterEvent(
                    seq=seq_start,
                    ts=utc_now_iso(),
                    event_type="error",
                    payload={"message": "invalid claude json event", "raw_line": raw_line},
                )
            ]

        if not isinstance(parsed, dict):
            return [
                AdapterEvent(
                    seq=seq_start,
                    ts=utc_now_iso(),
                    event_type="error",
                    payload={"message": "invalid claude event object", "raw": parsed},
                )
            ]

        ts = utc_now_iso()
        event_type = parsed.get("type")

        if event_type == "system" and parsed.get("subtype") == "init":
            events: list[AdapterEvent] = []
            session_id = parsed.get("session_id")
            next_seq = seq_start
            if isinstance(session_id, str) and session_id:
                events.append(
                    AdapterEvent(
                        seq=next_seq,
                        ts=ts,
                        event_type="thread_started",
                        payload={"thread_id": session_id},
                    )
                )
                next_seq += 1
            events.append(AdapterEvent(seq=next_seq, ts=ts, event_type="turn_started", payload={}))
            return events

        if event_type == "assistant":
            message = parsed.get("message")
            text = self._extract_assistant_text(message)
            if text:
                return [AdapterEvent(seq=seq_start, ts=ts, event_type="assistant_message", payload={"text": text})]
            return []

        if event_type == "result":
            is_error = bool(parsed.get("is_error"))
            subtype = parsed.get("subtype")
            status = "error" if is_error or (isinstance(subtype, str) and subtype not in ("success", "")) else "success"
            return [AdapterEvent(seq=seq_start, ts=ts, event_type="turn_completed", payload={"status": status})]

        if event_type == "error":
            message = parsed.get("message")
            message_text = message if isinstance(message, str) and message else "claude error"
            return [AdapterEvent(seq=seq_start, ts=ts, event_type="error", payload={"message": message_text, "raw": parsed})]

        return [AdapterEvent(seq=seq_start, ts=ts, event_type="reasoning", payload={"raw": parsed})]

    def extract_thread_id(self, event: AdapterEvent) -> str | None:
        if event.event_type != "thread_started":
            return None
        thread_id = event.payload.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
        return None

    async def _run_process(
        self,
        args: list[str],
        should_cancel: Any,
        workdir: str | None = None,
    ) -> AsyncIterator[AdapterEvent]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir or None,
        )

        seq = 1
        cancelled = False

        cancel_task: asyncio.Task[None] | None = None
        if should_cancel is not None:
            cancel_task = asyncio.create_task(self._cancel_monitor(process, should_cancel))

        try:
            assert process.stdout is not None
            while True:
                if should_cancel is not None and await should_cancel():
                    cancelled = True
                    if process.returncode is None:
                        process.terminate()
                line = await process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
                events = self.normalize_event(decoded, seq_start=seq)
                for event in events:
                    yield event
                    seq += 1

            stderr_text = ""
            if process.stderr is not None:
                stderr_text = (await process.stderr.read()).decode("utf-8", errors="replace").strip()

            return_code = await process.wait()
            if cancelled:
                yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="error", payload={"message": "cancelled"})
                seq += 1
                yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="turn_completed", payload={"status": "cancelled"})
                return

            if return_code != 0:
                yield AdapterEvent(
                    seq=seq,
                    ts=utc_now_iso(),
                    event_type="error",
                    payload={"message": f"claude exited with code {return_code}", "stderr": stderr_text[:4000]},
                )
                seq += 1
                yield AdapterEvent(seq=seq, ts=utc_now_iso(), event_type="turn_completed", payload={"status": "error"})
                return

        finally:
            if cancel_task is not None:
                cancel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_task

    async def _cancel_monitor(self, process: Process, should_cancel: Any) -> None:
        while process.returncode is None:
            await asyncio.sleep(0.5)
            try:
                if await should_cancel():
                    process.terminate()
                    return
            except Exception:
                return

    @staticmethod
    def _compose_prompt(preamble: str | None, prompt: str) -> str:
        if preamble and preamble.strip():
            return f"{preamble.strip()}\n\n[User Message]\n{prompt}"
        return prompt

    @staticmethod
    def _extract_assistant_text(message: Any) -> str:
        if not isinstance(message, dict):
            return ""
        if message.get("role") != "assistant":
            return ""
        content = message.get("content")
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        return "\n".join(parts).strip()
