from __future__ import annotations

import asyncio
import contextlib
import json
from asyncio.subprocess import Process
from typing import Any, AsyncIterator

from .base import AdapterEvent, AdapterResumeRequest, AdapterRunRequest, CliAdapter, utc_now_iso


class GeminiAdapter(CliAdapter):
    def __init__(self, gemini_bin: str = "gemini") -> None:
        self._gemini_bin = gemini_bin

    async def run_new_turn(self, request: AdapterRunRequest) -> AsyncIterator[AdapterEvent]:
        prompt = self._compose_prompt(request.preamble, request.prompt)
        # Non-interactive worker mode must not block on approval prompts.
        args = [self._gemini_bin, "--approval-mode", "yolo", "-o", "stream-json"]
        if request.model:
            args.extend(["--model", request.model])
        args.extend(["-p", prompt])

        async for event in self._run_process(args, request.should_cancel, request.workdir):
            yield event

    async def run_resume_turn(self, request: AdapterResumeRequest) -> AsyncIterator[AdapterEvent]:
        prompt = self._compose_prompt(request.preamble, request.prompt)
        # Non-interactive worker mode must not block on approval prompts.
        args = [self._gemini_bin, "--resume", request.thread_id, "--approval-mode", "yolo", "-o", "stream-json"]
        if request.model:
            args.extend(["--model", request.model])
        args.extend(["-p", prompt])

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
                    payload={"message": "invalid gemini json event", "raw_line": raw_line},
                )
            ]

        if not isinstance(parsed, dict):
            return [
                AdapterEvent(
                    seq=seq_start,
                    ts=utc_now_iso(),
                    event_type="error",
                    payload={"message": "invalid gemini event object", "raw": parsed},
                )
            ]

        ts = utc_now_iso()
        event_type = parsed.get("type")

        if event_type == "init":
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

        if event_type == "message":
            role = parsed.get("role")
            if role != "assistant":
                return []
            content = parsed.get("content")
            if isinstance(content, str) and content.strip():
                return [AdapterEvent(seq=seq_start, ts=ts, event_type="assistant_message", payload={"text": content})]
            return []

        if event_type == "result":
            status = parsed.get("status")
            normalized_status = status if isinstance(status, str) and status else "success"
            return [
                AdapterEvent(
                    seq=seq_start,
                    ts=ts,
                    event_type="turn_completed",
                    payload={"status": normalized_status},
                )
            ]

        if event_type == "error":
            message = parsed.get("message")
            message_text = message if isinstance(message, str) and message else "gemini error"
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
                    payload={"message": f"gemini exited with code {return_code}", "stderr": stderr_text[:4000]},
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
