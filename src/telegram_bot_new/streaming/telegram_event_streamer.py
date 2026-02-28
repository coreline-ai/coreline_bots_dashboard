from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from telegram_bot_new.adapters.base import AdapterEvent
from telegram_bot_new.telegram.client import TelegramApiError, TelegramClient, TelegramRateLimitError


MAX_MESSAGE_LEN = 3800
MAX_RETRIES = 5
_FENCED_CODE_BLOCK_RE = re.compile(r"```([A-Za-z0-9_+-]*)\r?\n(.*?)```", re.DOTALL)


@dataclass(slots=True)
class TurnStreamState:
    chat_id: int
    message_id: int
    text: str


class TelegramEventStreamer:
    def __init__(self, client: TelegramClient) -> None:
        self._client = client
        self._states: dict[str, TurnStreamState] = {}

    async def append_event(self, *, turn_id: str, chat_id: int, event: AdapterEvent) -> None:
        lines = self._format_event_lines(event)
        for line in lines:
            await self._append_line(turn_id=turn_id, chat_id=chat_id, line=line)

    async def append_delivery_error(self, *, turn_id: str, chat_id: int, message: str) -> None:
        error_event = AdapterEvent(
            seq=0,
            ts=datetime.now(tz=timezone.utc).isoformat(),
            event_type="delivery_error",
            payload={"message": message[:500]},
        )
        await self.append_event(turn_id=turn_id, chat_id=chat_id, event=error_event)

    async def close_turn(self, *, turn_id: str) -> None:
        self._states.pop(turn_id, None)

    def _format_event_lines(self, event: AdapterEvent) -> list[str]:
        hhmmss = self._to_hhmmss(event.ts)
        prefix = f"[{event.seq}][{hhmmss}][{event.event_type}] "
        body = self._event_payload_text(event)
        if not body:
            return [prefix.strip()]

        marker_size = 16
        max_body_size = max(200, MAX_MESSAGE_LEN - len(prefix) - marker_size)
        chunks = self._split_chunks(body, max_body_size)
        if len(chunks) == 1:
            return [f"{prefix}{chunks[0]}".strip()]
        return [f"{prefix}({idx + 1}/{len(chunks)}) {chunk}".strip() for idx, chunk in enumerate(chunks)]

    def _event_payload_text(self, event: AdapterEvent) -> str:
        payload = event.payload
        if event.event_type in ("assistant_message", "reasoning"):
            text = payload.get("text")
            if isinstance(text, str) and text.strip():
                return text

        if event.event_type in ("command_started", "command_completed"):
            command = payload.get("command")
            parts: list[str] = []
            if isinstance(command, str) and command:
                parts.append(command)
            if event.event_type == "command_completed":
                if "exit_code" in payload:
                    parts.append(f"exit_code={payload.get('exit_code')}")
                output = payload.get("aggregated_output")
                if isinstance(output, str) and output:
                    parts.append(output)
            return "\n".join(parts).strip()

        if event.event_type == "error":
            message = payload.get("message")
            if isinstance(message, str):
                return message

        return json.dumps(payload, ensure_ascii=False)

    def _to_hhmmss(self, iso_ts: str) -> str:
        try:
            parsed = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).strftime("%H:%M:%S")
        except ValueError:
            return "00:00:00"

    async def _send_with_retry(self, *, chat_id: int, text: str) -> int:
        for attempt in range(MAX_RETRIES):
            try:
                rendered_text, parse_mode = self._render_for_telegram(text[:MAX_MESSAGE_LEN])
                return await self._client.send_message(chat_id=chat_id, text=rendered_text, parse_mode=parse_mode)
            except TelegramRateLimitError as error:
                await asyncio.sleep(error.retry_after)
            except TelegramApiError:
                if attempt >= MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        raise RuntimeError("failed to send telegram message after retries")

    async def _edit_with_retry(self, *, chat_id: int, message_id: int, text: str) -> None:
        for attempt in range(MAX_RETRIES):
            try:
                rendered_text, parse_mode = self._render_for_telegram(text[:MAX_MESSAGE_LEN])
                await self._client.edit_message(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=rendered_text,
                    parse_mode=parse_mode,
                )
                return
            except TelegramRateLimitError as error:
                await asyncio.sleep(error.retry_after)
            except TelegramApiError:
                if attempt >= MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        raise RuntimeError("failed to edit telegram message after retries")

    async def _append_line(self, *, turn_id: str, chat_id: int, line: str) -> None:
        state = self._states.get(turn_id)

        if state is None:
            message_id = await self._send_with_retry(chat_id=chat_id, text=line)
            self._states[turn_id] = TurnStreamState(chat_id=chat_id, message_id=message_id, text=line)
            return

        candidate = f"{state.text}\n{line}"
        if len(candidate) <= MAX_MESSAGE_LEN:
            await self._edit_with_retry(chat_id=state.chat_id, message_id=state.message_id, text=candidate)
            state.text = candidate
            return

        continuation_text = f"[continued]\n{line}"
        message_id = await self._send_with_retry(chat_id=state.chat_id, text=continuation_text)
        self._states[turn_id] = TurnStreamState(chat_id=chat_id, message_id=message_id, text=continuation_text)

    def _render_for_telegram(self, text: str) -> tuple[str, str | None]:
        if "```" not in text:
            return text, None

        rendered = self._render_fenced_code_blocks_as_html(text)
        if len(rendered) > MAX_MESSAGE_LEN:
            return text, None
        return rendered, "HTML"

    def _render_fenced_code_blocks_as_html(self, text: str) -> str:
        result: list[str] = []
        cursor = 0

        for match in _FENCED_CODE_BLOCK_RE.finditer(text):
            before = text[cursor : match.start()]
            if before:
                result.append(html.escape(before).replace("\n", "<br>"))

            language = (match.group(1) or "").strip()
            code = match.group(2) or ""
            code_escaped = html.escape(code)
            if language:
                lang_escaped = html.escape(language)
                result.append(f'<pre><code class="language-{lang_escaped}">{code_escaped}</code></pre>')
            else:
                result.append(f"<pre><code>{code_escaped}</code></pre>")

            cursor = match.end()

        tail = text[cursor:]
        if tail:
            result.append(html.escape(tail).replace("\n", "<br>"))

        if not result:
            return html.escape(text)
        return "".join(result)

    def _split_chunks(self, text: str, chunk_size: int) -> list[str]:
        if len(text) <= chunk_size:
            return [text]
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
