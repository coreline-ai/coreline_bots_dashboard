from __future__ import annotations

import asyncio
import contextlib
import json
from asyncio.subprocess import Process
from typing import Any, AsyncIterator

from .base import AdapterEvent, AdapterResumeRequest, AdapterRunRequest, CliAdapter, utc_now_iso


class CodexAdapter(CliAdapter):
    def __init__(self, codex_bin: str = "codex") -> None:
        self._codex_bin = codex_bin

    @staticmethod
    def _base_exec_args(codex_bin: str) -> list[str]:
        # Force a safe effort level for non-interactive workers so a user's global
        # Codex config (e.g. model_reasoning_effort="xhigh") cannot break gpt-5 runs.
        return [
            codex_bin,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "-c",
            'model_reasoning_effort="high"',
        ]

    async def run_new_turn(self, request: AdapterRunRequest) -> AsyncIterator[AdapterEvent]:
        prompt = self._compose_prompt(request.preamble, request.prompt)
        args = self._base_exec_args(self._codex_bin)
        if request.model:
            args.extend(["-m", request.model])
        if request.sandbox:
            args.extend(["-s", request.sandbox])
        args.append(prompt)

        async for event in self._run_process(args, request.should_cancel, request.workdir):
            yield event

    async def run_resume_turn(self, request: AdapterResumeRequest) -> AsyncIterator[AdapterEvent]:
        prompt = self._compose_prompt(request.preamble, request.prompt)
        args = self._base_exec_args(self._codex_bin)
        if request.model:
            args.extend(["-m", request.model])
        if request.sandbox:
            args.extend(["-s", request.sandbox])
        args.extend(["resume", request.thread_id, prompt])

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
                    payload={"message": "invalid codex json event", "raw_line": raw_line},
                )
            ]

        event_type = parsed.get("type")
        ts = utc_now_iso()

        if event_type == "thread.started":
            thread_id = parsed.get("thread_id")
            if not thread_id and isinstance(parsed.get("thread"), dict):
                thread_id = parsed["thread"].get("id")
            return [AdapterEvent(seq=seq_start, ts=ts, event_type="thread_started", payload={"thread_id": thread_id})]

        if event_type == "turn.started":
            return [AdapterEvent(seq=seq_start, ts=ts, event_type="turn_started", payload={})]

        if event_type == "turn.completed":
            return [
                AdapterEvent(
                    seq=seq_start,
                    ts=ts,
                    event_type="turn_completed",
                    payload={"usage": parsed.get("usage", {}), "status": parsed.get("status", "success")},
                )
            ]

        if event_type in ("item.started", "item.completed"):
            item = parsed.get("item") if isinstance(parsed.get("item"), dict) else {}
            item_type = item.get("type")
            status = item.get("status")

            if item_type == "reasoning":
                return [AdapterEvent(seq=seq_start, ts=ts, event_type="reasoning", payload={"text": self._extract_text(item)})]

            if item_type in ("agent_message", "assistant_message", "message"):
                return [AdapterEvent(seq=seq_start, ts=ts, event_type="assistant_message", payload={"text": self._extract_text(item)})]

            if item_type == "command_execution" and event_type == "item.started":
                return [
                    AdapterEvent(
                        seq=seq_start,
                        ts=ts,
                        event_type="command_started",
                        payload={"command": self._extract_command(item), "status": status or "in_progress"},
                    )
                ]

            if item_type == "command_execution" and event_type == "item.completed":
                return [
                    AdapterEvent(
                        seq=seq_start,
                        ts=ts,
                        event_type="command_completed",
                        payload={
                            "command": self._extract_command(item),
                            "exit_code": item.get("exit_code"),
                            "aggregated_output": item.get("aggregated_output", ""),
                            "status": status or "completed",
                        },
                    )
                ]

        if event_type == "error":
            return [
                AdapterEvent(
                    seq=seq_start,
                    ts=ts,
                    event_type="error",
                    payload={"message": parsed.get("message", "codex error"), "raw": parsed},
                )
            ]

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
                    payload={"message": f"codex exited with code {return_code}", "stderr": stderr_text[:4000]},
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
    def _extract_text(item: dict[str, Any]) -> str:
        text = item.get("text")
        if isinstance(text, str):
            return text

        content = item.get("content")
        if not isinstance(content, list):
            return ""

        parts: list[str] = []
        for piece in content:
            if isinstance(piece, dict):
                value = piece.get("text")
                if isinstance(value, str):
                    parts.append(value)
        return "\n".join(parts)

    @staticmethod
    def _extract_command(item: dict[str, Any]) -> str:
        command = item.get("command")
        if isinstance(command, str):
            return command
        if isinstance(command, list):
            return " ".join(str(part) for part in command)
        return ""
