from __future__ import annotations

import asyncio
import argparse
import mimetypes
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from telegram_bot_new.adapters.base import AdapterEvent
from telegram_bot_new.adapters.codex_adapter import CodexAdapter
from telegram_bot_new.services.youtube_search_service import YoutubeSearchService


MAX_MESSAGE_LEN = 3800
MAX_RETRIES = 5
MAX_REASONING_PREVIEW = 1200
MAX_COMMAND_OUTPUT_PREVIEW = 1200
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
HTML_SUFFIXES = {".html", ".htm"}
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}


class MockApiError(RuntimeError):
    pass


class MockRateLimitError(MockApiError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(f"rate limited retry_after={self.retry_after}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex bridge for mock messenger")
    parser.add_argument("--base-url", default="http://127.0.0.1:9082")
    parser.add_argument("--token", default="mock_token_1")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model", default=None)
    parser.add_argument("--sandbox", default="workspace-write")
    parser.add_argument("--heartbeat-sec", type=float, default=3.0)
    parser.add_argument("--run-timeout-sec", type=int, default=900)
    parser.add_argument("--poll-interval-sec", type=float, default=0.5)
    return parser


def _utc_hhmmss() -> str:
    return datetime.now(tz=timezone.utc).strftime("%H:%M:%S")


def _post_json(client: httpx.Client, base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{base_url}{path}", json=payload)
    try:
        body = response.json()
    except Exception as error:
        raise MockApiError(f"invalid json response path={path} status={response.status_code}") from error

    if response.status_code == 429:
        retry_after = 1
        if isinstance(body, dict):
            params = body.get("parameters")
            if isinstance(params, dict) and isinstance(params.get("retry_after"), int):
                retry_after = max(1, int(params["retry_after"]))
        raise MockRateLimitError(retry_after=retry_after)

    if response.status_code >= 400:
        description = body.get("description") if isinstance(body, dict) else None
        raise MockApiError(f"http {response.status_code} path={path}: {description or body}")

    if not isinstance(body, dict) or body.get("ok") is not True:
        raise MockApiError(f"mock api error path={path} body={body}")

    return body


def _send_message(client: httpx.Client, base_url: str, token: str, chat_id: int, text: str) -> int:
    for attempt in range(MAX_RETRIES):
        try:
            response = _post_json(
                client,
                base_url,
                f"/bot{token}/sendMessage",
                {"chat_id": chat_id, "text": text[:MAX_MESSAGE_LEN]},
            )
            result = response.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
                raise MockApiError("sendMessage missing message_id")
            return int(result["message_id"])
        except MockRateLimitError as error:
            time.sleep(error.retry_after)
        except Exception:
            if attempt >= MAX_RETRIES - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise MockApiError("failed to send message")


def _edit_message(client: httpx.Client, base_url: str, token: str, chat_id: int, message_id: int, text: str) -> None:
    for attempt in range(MAX_RETRIES):
        try:
            _post_json(
                client,
                base_url,
                f"/bot{token}/editMessageText",
                {"chat_id": chat_id, "message_id": message_id, "text": text[:MAX_MESSAGE_LEN]},
            )
            return
        except MockRateLimitError as error:
            time.sleep(error.retry_after)
        except Exception:
            if attempt >= MAX_RETRIES - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise MockApiError("failed to edit message")


def _send_document(
    client: httpx.Client,
    base_url: str,
    token: str,
    chat_id: int,
    file_path: Path,
    caption: str | None = None,
) -> None:
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    for attempt in range(MAX_RETRIES):
        try:
            with file_path.open("rb") as fh:
                response = client.post(
                    f"{base_url}/bot{token}/sendDocument",
                    data={"chat_id": str(chat_id), "caption": caption or ""},
                    files={"document": (file_path.name, fh, media_type)},
                )
            try:
                body = response.json()
            except Exception as error:
                raise MockApiError(f"invalid json response in sendDocument status={response.status_code}") from error

            if response.status_code == 429:
                retry_after = 1
                if isinstance(body, dict):
                    params = body.get("parameters")
                    if isinstance(params, dict) and isinstance(params.get("retry_after"), int):
                        retry_after = max(1, int(params["retry_after"]))
                raise MockRateLimitError(retry_after=retry_after)

            if response.status_code >= 400 or not isinstance(body, dict) or body.get("ok") is not True:
                description = body.get("description") if isinstance(body, dict) else None
                raise MockApiError(f"sendDocument failed: {description or body}")
            return
        except MockRateLimitError as error:
            time.sleep(error.retry_after)
        except Exception:
            if attempt >= MAX_RETRIES - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise MockApiError("failed to send document")


def _extract_local_paths(text: str, *, suffixes: set[str]) -> list[Path]:
    if not text or not text.strip():
        return []

    suffix_pattern = "|".join(ext.lstrip(".") for ext in sorted(suffixes))
    candidates: list[str] = []
    candidates.extend(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text))
    candidates.extend(re.findall(r"\[[^\]]*\]\(([^)]+)\)", text))
    candidates.extend(
        re.findall(
            rf"['\"]([^'\"]+\.(?:{suffix_pattern}))['\"]",
            text,
            flags=re.IGNORECASE,
        )
    )
    candidates.extend(
        re.findall(
            rf"((?:[A-Za-z]:)?(?:[./\\][^\s'\"`<>|]+)+\.(?:{suffix_pattern}))",
            text,
            flags=re.IGNORECASE,
        )
    )

    paths: list[Path] = []
    seen: set[str] = set()
    for raw in candidates:
        candidate = raw.strip().strip("\"'").strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("data:"):
            continue
        resolved = Path(candidate).expanduser()
        if not resolved.is_absolute():
            resolved = (Path.cwd() / resolved).resolve()
        else:
            resolved = resolved.resolve()
        if resolved.suffix.lower() not in suffixes:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        if resolved.exists() and resolved.is_file():
            seen.add(key)
            paths.append(resolved)
    return paths


def _extract_local_image_paths(text: str) -> list[Path]:
    return _extract_local_paths(text, suffixes=IMAGE_SUFFIXES)


def _extract_local_html_paths(text: str) -> list[Path]:
    return _extract_local_paths(text, suffixes=HTML_SUFFIXES)


def _looks_like_image_request(prompt: str) -> bool:
    text = (prompt or "").lower()
    if not text:
        return False
    keywords = [
        "image",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "photo",
        "diagram",
        "chart",
        "plot",
        "figure",
        "draw",
        "render",
        "\uc774\ubbf8\uc9c0",
        "\uc0ac\uc9c4",
        "\uadf8\ub9bc",
        "\ucc28\ud2b8",
        "\uadf8\ub798\ud504",
    ]
    return any(keyword in text for keyword in keywords)


def _looks_like_html_request(prompt: str) -> bool:
    text = (prompt or "").lower()
    if not text:
        return False
    keywords = [
        "html",
        "css",
        "landing page",
        "web page",
        "webpage",
        "site",
        "\ub79c\ub529",
        "\uc6f9\ud398\uc774\uc9c0",
        "\ud398\uc774\uc9c0",
    ]
    return any(keyword in text for keyword in keywords)


def _augment_prompt_for_generation_request(prompt: str) -> str:
    result = prompt
    if _looks_like_image_request(prompt):
        result = (
            f"{result}\n\n[Image Delivery Contract]\n"
            "If you generate an image file, save it as a local file and include at least one markdown image path.\n"
            "Preferred format:\n"
            "![generated](./.mock_messenger/generated/<file>.png)\n"
            "Use a real existing path only."
        )
    if _looks_like_html_request(prompt):
        result = (
            f"{result}\n\n[HTML Delivery Contract]\n"
            "If you generate an HTML page, save it as a local file and include a markdown link to that exact file.\n"
            "Also generate one preview image (png) for Telegram chat preview.\n"
            "Preferred format:\n"
            "[landing page](./.mock_messenger/generated/<file>.html)\n"
            "![preview](./.mock_messenger/generated/<file>.png)\n"
            "Use inline CSS if possible so single-file preview works."
        )
    return result


def _parse_youtube_search_request(text: str) -> tuple[bool, str | None]:
    lowered = text.lower()
    youtube_variants = (
        "youtube",
        "\uc720\ud29c\ube0c",
        "\uc720\ud22c\ube0c",
        "\uc720\ud2b8\ube0c",
        "\uc720\ud2b8\ubdf0",
    )
    has_youtube = any(variant in lowered for variant in youtube_variants)
    if not has_youtube:
        return (False, None)

    search_hints = (
        "search",
        "find",
        "recommend",
        "show",
        "\ucc3e\uc544",
        "\uac80\uc0c9",
        "\ucd94\ucc9c",
        "\ubcf4\uc5ec",
    )
    if not any(hint in lowered for hint in search_hints):
        return (False, None)

    cleaned = text
    for pattern in (
        r"(?i)\byoutube\b",
        "\uc720\ud29c\ube0c",
        "\uc720\ud22c\ube0c",
        "\uc720\ud2b8\ube0c",
        "\uc720\ud2b8\ubdf0",
        "\ub3d9\uc601\uc0c1",
        "\uc601\uc0c1",
        "\ucc3e\uc544\uc918",
        "\ucc3e\uc544 \uc918",
        "\ucc3e\uc544",
        "\uac80\uc0c9\ud574\uc918",
        "\uac80\uc0c9\ud574 \uc918",
        "\uac80\uc0c9",
        "\ucd94\ucc9c\ud574\uc918",
        "\ucd94\ucc9c\ud574 \uc918",
        "\ucd94\ucc9c",
        "\ubcf4\uc5ec\uc918",
        "\ubcf4\uc5ec \uc918",
        "\ubcf4\uc5ec",
        "\ubbf8\ub9ac\ubcf4\uae30",
        "\ubbf8\ub9ac \ubcf4\uae30",
        "\ud615\uc2dd\uc73c\ub85c",
        "\ud615\uc2dd",
        "please",
        "for me",
    ):
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?\n\t")
    return (True, cleaned or None)


def _handle_youtube_search(
    *,
    client: httpx.Client,
    youtube_search: YoutubeSearchService,
    base_url: str,
    token: str,
    chat_id: int,
    query: str,
) -> None:
    normalized_query = " ".join(query.split())
    if not normalized_query:
        _send_message(client, base_url, token, chat_id, "YouTube 검색어를 입력해 주세요.")
        return

    try:
        result = asyncio.run(youtube_search.search_first_video(normalized_query))
    except Exception as error:
        _send_message(client, base_url, token, chat_id, f"YouTube 검색 중 오류가 발생했습니다: {error}")
        return

    if result is None:
        _send_message(client, base_url, token, chat_id, f"YouTube 검색 결과를 찾지 못했습니다: {normalized_query}")
        return

    # Send the watch URL only so Telegram-style clients show a native preview card.
    _send_message(client, base_url, token, chat_id, result.url)


def _find_recent_files(
    *,
    since_epoch: float,
    suffixes: set[str],
    limit: int = 3,
    roots: list[Path] | None = None,
) -> list[Path]:
    scan_roots = roots if roots is not None else [Path.cwd(), Path(tempfile.gettempdir())]
    discovered: list[tuple[float, Path]] = []
    seen: set[str] = set()
    cutoff = since_epoch - 2.0

    for root in scan_roots:
        try:
            resolved_root = root.resolve()
        except Exception:
            continue
        if not resolved_root.exists() or not resolved_root.is_dir():
            continue

        for dirpath, dirnames, filenames in os.walk(resolved_root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
            for name in filenames:
                suffix = Path(name).suffix.lower()
                if suffix not in suffixes:
                    continue
                path = Path(dirpath) / name
                key = str(path).lower()
                if key in seen:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size <= 0 or stat.st_mtime < cutoff:
                    continue
                seen.add(key)
                discovered.append((stat.st_mtime, path.resolve()))

    discovered.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in discovered[: max(1, limit)]]


def _find_recent_image_files(*, since_epoch: float, limit: int = 3, roots: list[Path] | None = None) -> list[Path]:
    return _find_recent_files(since_epoch=since_epoch, suffixes=IMAGE_SUFFIXES, limit=limit, roots=roots)


def _find_recent_html_files(*, since_epoch: float, limit: int = 3, roots: list[Path] | None = None) -> list[Path]:
    return _find_recent_files(since_epoch=since_epoch, suffixes=HTML_SUFFIXES, limit=limit, roots=roots)


def _create_demo_landing_page() -> Path:
    generated_dir = (Path.cwd() / ".mock_messenger" / "generated").resolve()
    generated_dir.mkdir(parents=True, exist_ok=True)
    filename = f"landing_demo_{int(time.time())}.html"
    path = generated_dir / filename
    html = """<!doctype html>
<html lang=\"ko\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Flower Landing Demo</title>
  <style>
    :root { --bg: #f7f2e9; --ink: #2b2b2b; --accent: #0d7c66; --card: #ffffff; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: 'Segoe UI', sans-serif; color: var(--ink); background: radial-gradient(circle at 20% 10%, #fff8dc, var(--bg) 45%); }
    .hero { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
    .card { width: min(900px, 96vw); background: var(--card); border: 1px solid #ddd3c1; border-radius: 16px; padding: 28px; box-shadow: 0 10px 36px rgba(0,0,0,.07); }
    h1 { margin: 0 0 10px; font-size: clamp(28px, 5vw, 56px); letter-spacing: -0.02em; }
    p { margin: 0 0 18px; line-height: 1.55; }
    .cta { display: inline-block; padding: 12px 18px; border-radius: 999px; background: var(--accent); color: #fff; text-decoration: none; font-weight: 700; }
    .strip { margin-top: 18px; display: grid; gap: 10px; grid-template-columns: repeat(3, minmax(0,1fr)); }
    .box { border: 1px solid #e7ddca; border-radius: 12px; padding: 12px; background: #fffcf6; }
  </style>
</head>
<body>
  <section class=\"hero\">
    <article class=\"card\">
      <h1>Bloom Studio</h1>
      <p>꽃 사진, 카드, 브랜딩 비주얼을 빠르게 제작하는 데모 랜딩 페이지입니다. HTML + CSS 단일 파일로 구성되어 프리뷰에 바로 표시됩니다.</p>
      <a class=\"cta\" href=\"#\">무료로 시작하기</a>
      <div class=\"strip\">
        <div class=\"box\">실시간 생성</div>
        <div class=\"box\">빠른 커스터마이징</div>
        <div class=\"box\">모바일 반응형</div>
      </div>
    </article>
  </section>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path
def _send_long_message(client: httpx.Client, base_url: str, token: str, chat_id: int, text: str) -> None:
    if len(text) <= MAX_MESSAGE_LEN:
        _send_message(client, base_url, token, chat_id, text)
        return
    chunks = _split_chunks(text, MAX_MESSAGE_LEN - 20)
    for index, chunk in enumerate(chunks, start=1):
        prefix = "" if index == 1 else f"[continued {index}/{len(chunks)}]\n"
        _send_message(client, base_url, token, chat_id, f"{prefix}{chunk}")


def _split_chunks(text: str, chunk_size: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _event_payload_text(event: AdapterEvent) -> str:
    def truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return f"{value[:limit]}\n...[truncated {len(value) - limit} chars]"

    payload = event.payload
    if event.event_type in ("assistant_message", "reasoning"):
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return truncate(text, MAX_REASONING_PREVIEW)
        stderr = payload.get("stderr")
        if isinstance(stderr, str) and stderr.strip():
            return truncate(stderr, MAX_REASONING_PREVIEW)

    if event.event_type in ("command_started", "command_completed"):
        command = payload.get("command")
        parts: list[str] = []
        if isinstance(command, str) and command:
            parts.append(command)
        if event.event_type == "command_completed":
            if "exit_code" in payload:
                parts.append(f"exit_code={payload.get('exit_code')}")
            output = payload.get("aggregated_output")
            if isinstance(output, str) and output.strip():
                parts.append(truncate(output.strip(), MAX_COMMAND_OUTPUT_PREVIEW))
        return "\n".join(parts).strip()

    if event.event_type == "error":
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return truncate(message.strip(), MAX_REASONING_PREVIEW)

    return truncate(str(payload), MAX_REASONING_PREVIEW)


def _format_event_lines(event: AdapterEvent) -> list[str]:
    try:
        parsed = datetime.fromisoformat(event.ts.replace("Z", "+00:00"))
        hhmmss = parsed.astimezone(timezone.utc).strftime("%H:%M:%S")
    except Exception:
        hhmmss = "00:00:00"

    prefix = f"[{event.seq}][{hhmmss}][{event.event_type}] "
    body = _event_payload_text(event)
    if not body:
        return [prefix.strip()]

    max_body_size = max(200, MAX_MESSAGE_LEN - len(prefix) - 16)
    chunks = _split_chunks(body, max_body_size)
    if len(chunks) == 1:
        return [f"{prefix}{chunks[0]}".strip()]
    return [f"{prefix}({idx + 1}/{len(chunks)}) {chunk}".strip() for idx, chunk in enumerate(chunks)]


def _format_status_line(message: str) -> str:
    return f"[~][{_utc_hhmmss()}][bridge_status] {message}"


@dataclass(slots=True)
class LiveMessageState:
    chat_id: int
    message_id: int
    text: str


class LiveMessageBuffer:
    def __init__(self, *, client: httpx.Client, base_url: str, token: str, chat_id: int) -> None:
        self._client = client
        self._base_url = base_url
        self._token = token
        self._chat_id = chat_id
        self._state: LiveMessageState | None = None

    def append_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        if self._state is None:
            message_id = _send_message(self._client, self._base_url, self._token, self._chat_id, line)
            self._state = LiveMessageState(chat_id=self._chat_id, message_id=message_id, text=line)
            return

        candidate = f"{self._state.text}\n{line}"
        if len(candidate) <= MAX_MESSAGE_LEN:
            _edit_message(
                self._client,
                self._base_url,
                self._token,
                self._state.chat_id,
                self._state.message_id,
                candidate,
            )
            self._state.text = candidate
            return

        continuation = f"[continued]\n{line}"
        message_id = _send_message(self._client, self._base_url, self._token, self._chat_id, continuation)
        self._state = LiveMessageState(chat_id=self._chat_id, message_id=message_id, text=continuation)


def _pipe_reader(
    *,
    pipe: Any,
    source: str,
    output_queue: "queue.Queue[tuple[str, str | None]]",
) -> None:
    if pipe is None:
        output_queue.put((source, None))
        return

    try:
        while True:
            line = pipe.readline()
            if line == "":
                break
            output_queue.put((source, line.rstrip("\r\n")))
    finally:
        output_queue.put((source, None))


def _build_codex_command(
    *,
    codex_bin: str,
    prompt: str,
    thread_id: str | None,
    model: str | None,
    sandbox: str,
) -> list[str]:
    cmd = [codex_bin, "exec", "--json", "--skip-git-repo-check"]
    if model:
        cmd.extend(["-m", model])
    if sandbox:
        cmd.extend(["-s", sandbox])
    if thread_id:
        cmd.extend(["resume", thread_id, prompt])
    else:
        cmd.append(prompt)
    return cmd


def _cmd_preview(*, codex_bin: str, thread_id: str | None, model: str | None, sandbox: str) -> str:
    parts = [codex_bin, "exec", "--json", "--skip-git-repo-check"]
    if model:
        parts.extend(["-m", model])
    if sandbox:
        parts.extend(["-s", sandbox])
    if thread_id:
        parts.extend(["resume", thread_id, "<prompt>"])
    else:
        parts.append("<prompt>")
    return " ".join(parts)


@dataclass(slots=True)
class CodexRunResult:
    thread_id: str | None
    assistant_text: str
    return_code: int
    stderr_text: str
    status: str
    event_count: int
    timed_out: bool


def _run_codex_stream(
    *,
    client: httpx.Client,
    base_url: str,
    token: str,
    chat_id: int,
    prompt: str,
    thread_id: str | None,
    codex_bin: str,
    model: str | None,
    sandbox: str,
    heartbeat_sec: float,
    run_timeout_sec: int,
) -> CodexRunResult:
    adapter = CodexAdapter(codex_bin=codex_bin)
    live = LiveMessageBuffer(client=client, base_url=base_url, token=token, chat_id=chat_id)
    live.append_line(_format_status_line(f"turn started mode={'resume' if thread_id else 'new'}"))
    live.append_line(_format_status_line(_cmd_preview(codex_bin=codex_bin, thread_id=thread_id, model=model, sandbox=sandbox)))

    cmd = _build_codex_command(
        codex_bin=codex_bin,
        prompt=prompt,
        thread_id=thread_id,
        model=model,
        sandbox=sandbox,
    )

    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except Exception as error:
        live.append_line(_format_status_line(f"failed to start codex: {error}"))
        return CodexRunResult(
            thread_id=thread_id,
            assistant_text="",
            return_code=127,
            stderr_text=str(error),
            status="error",
            event_count=0,
            timed_out=False,
        )

    line_queue: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
    stdout_thread = threading.Thread(
        target=_pipe_reader,
        kwargs={"pipe": process.stdout, "source": "stdout", "output_queue": line_queue},
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_pipe_reader,
        kwargs={"pipe": process.stderr, "source": "stderr", "output_queue": line_queue},
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    seq = 1
    event_count = 0
    assistant_parts: list[str] = []
    stderr_parts: list[str] = []
    resolved_thread_id = thread_id
    status = "unknown"
    timed_out = False
    start_monotonic = time.monotonic()
    last_heartbeat = start_monotonic
    stdout_done = False
    stderr_done = False

    while True:
        now = time.monotonic()
        elapsed = now - start_monotonic

        if run_timeout_sec > 0 and elapsed >= run_timeout_sec and process.poll() is None and not timed_out:
            timed_out = True
            live.append_line(_format_status_line(f"timeout reached ({run_timeout_sec}s), terminating codex"))
            try:
                process.terminate()
            except Exception:
                pass

        try:
            source, line = line_queue.get(timeout=0.4)
        except queue.Empty:
            if now - last_heartbeat >= heartbeat_sec:
                live.append_line(_format_status_line(f"running... elapsed={int(elapsed)}s"))
                last_heartbeat = now
            if process.poll() is not None and stdout_done and stderr_done and line_queue.empty():
                break
            continue

        if line is None:
            if source == "stdout":
                stdout_done = True
            if source == "stderr":
                stderr_done = True
            if process.poll() is not None and stdout_done and stderr_done and line_queue.empty():
                break
            continue

        if source == "stderr":
            if line.strip():
                stderr_parts.append(line.strip())
            continue

        normalized = adapter.normalize_event(line, seq_start=seq)
        if not normalized:
            continue

        for event in normalized:
            event_count += 1
            for formatted in _format_event_lines(event):
                live.append_line(formatted)

            new_thread = adapter.extract_thread_id(event)
            if new_thread:
                resolved_thread_id = new_thread

            if event.event_type == "assistant_message":
                text = event.payload.get("text")
                if isinstance(text, str) and text.strip():
                    assistant_parts.append(text.strip())

            if event.event_type == "turn_completed":
                maybe_status = event.payload.get("status")
                if isinstance(maybe_status, str) and maybe_status:
                    status = maybe_status

            seq += 1

    try:
        return_code = process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        return_code = process.wait()

    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)

    stderr_text = "\n".join(stderr_parts).strip()
    assistant_text = "\n".join(part for part in assistant_parts if part).strip()

    if status == "unknown":
        if timed_out:
            status = "timeout"
        elif return_code != 0:
            status = "error"
        else:
            status = "success"

    if return_code != 0:
        live.append_line(_format_status_line(f"codex exited with code={return_code}"))
    if stderr_text:
        stderr_preview = stderr_text[:900]
        live.append_line(f"[~][{_utc_hhmmss()}][stderr] {stderr_preview}")
    live.append_line(_format_status_line(f"turn finished status={status} events={event_count}"))

    return CodexRunResult(
        thread_id=resolved_thread_id,
        assistant_text=assistant_text,
        return_code=return_code,
        stderr_text=stderr_text,
        status=status,
        event_count=event_count,
        timed_out=timed_out,
    )


def main() -> None:
    args = build_parser().parse_args()
    base_url = args.base_url.rstrip("/")
    token = args.token
    codex_bin = args.codex_bin
    model = args.model
    sandbox = args.sandbox
    heartbeat_sec = max(1.0, float(args.heartbeat_sec))
    run_timeout_sec = max(30, int(args.run_timeout_sec))
    poll_interval = max(0.1, args.poll_interval_sec)

    offset: int | None = None
    thread_by_chat: dict[int, str] = {}
    sent_file_paths_by_chat: dict[int, set[str]] = {}
    youtube_search = YoutubeSearchService()

    with httpx.Client(timeout=90) as client:
        while True:
            try:
                payload: dict[str, int] = {"limit": 20, "timeout": 1}
                if offset is not None:
                    payload["offset"] = offset

                response = _post_json(client, base_url, f"/bot{token}/getUpdates", payload)
                result = response.get("result", [])
                updates = result if isinstance(result, list) else []
                if not updates:
                    time.sleep(poll_interval)
                    continue

                for update in updates:
                    if not isinstance(update, dict):
                        continue

                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1

                    message = update.get("message") if isinstance(update.get("message"), dict) else {}
                    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
                    chat_id = chat.get("id")
                    user_text = message.get("text")
                    if not isinstance(chat_id, int) or not isinstance(user_text, str) or not user_text.strip():
                        continue

                    text = user_text.strip()

                    if text == "/youtube" or text == "/yt" or text.startswith("/youtube ") or text.startswith("/yt "):
                        command, *parts = text.split(maxsplit=1)
                        query = parts[0].strip() if parts else ""
                        if not query:
                            _send_message(client, base_url, token, chat_id, "Usage: /youtube <query>")
                        else:
                            _handle_youtube_search(
                                client=client,
                                youtube_search=youtube_search,
                                base_url=base_url,
                                token=token,
                                chat_id=chat_id,
                                query=query,
                            )
                        continue

                    youtube_intent, youtube_query = _parse_youtube_search_request(text)
                    if youtube_intent:
                        if not youtube_query:
                            _send_message(
                                client,
                                base_url,
                                token,
                                chat_id,
                                "YouTube 검색어를 함께 입력해 주세요. 예: 백종원 유튜브 찾아줘",
                            )
                        else:
                            _handle_youtube_search(
                                client=client,
                                youtube_search=youtube_search,
                                base_url=base_url,
                                token=token,
                                chat_id=chat_id,
                                query=youtube_query,
                            )
                        continue

                    if text == "/new":
                        thread_by_chat.pop(chat_id, None)
                        _send_message(client, base_url, token, chat_id, "[bridge] session reset: next turn starts a new thread")
                        continue

                    if text == "/status":
                        current_thread = thread_by_chat.get(chat_id)
                        if current_thread:
                            _send_message(client, base_url, token, chat_id, f"[bridge] status: active thread_id={current_thread}")
                        else:
                            _send_message(client, base_url, token, chat_id, "[bridge] status: no active thread yet")
                        continue

                    if text == "/demo-landing":
                        demo_path = _create_demo_landing_page()
                        _send_document(
                            client,
                            base_url,
                            token,
                            chat_id,
                            demo_path,
                            caption=f"[bridge] demo landing page: {demo_path.name}",
                        )
                        continue

                    thread_id = thread_by_chat.get(chat_id)
                    run_started_epoch = time.time()
                    run_prompt = _augment_prompt_for_generation_request(text)
                    run_result = _run_codex_stream(
                        client=client,
                        base_url=base_url,
                        token=token,
                        chat_id=chat_id,
                        prompt=run_prompt,
                        thread_id=thread_id,
                        codex_bin=codex_bin,
                        model=model,
                        sandbox=sandbox,
                        heartbeat_sec=heartbeat_sec,
                        run_timeout_sec=run_timeout_sec,
                    )
                    if run_result.thread_id:
                        thread_by_chat[chat_id] = run_result.thread_id

                    if run_result.return_code != 0 and not run_result.assistant_text:
                        reason = "timeout" if run_result.timed_out else f"exit_code={run_result.return_code}"
                        stderr_preview = run_result.stderr_text[:1500]
                        detail = stderr_preview if stderr_preview else "no stderr output"
                        _send_long_message(
                            client,
                            base_url,
                            token,
                            chat_id,
                            f"[bridge] codex failed ({reason})\n{detail}",
                        )
                        continue

                    if run_result.assistant_text:
                        _send_long_message(client, base_url, token, chat_id, run_result.assistant_text)
                        image_paths = _extract_local_image_paths(run_result.assistant_text)
                        if not image_paths and _looks_like_image_request(text):
                            image_paths = _find_recent_image_files(since_epoch=run_started_epoch, limit=3)

                        html_paths = _extract_local_html_paths(run_result.assistant_text)
                        if not html_paths and _looks_like_html_request(text):
                            html_paths = _find_recent_html_files(since_epoch=run_started_epoch, limit=2)

                        sent_for_chat = sent_file_paths_by_chat.setdefault(chat_id, set())
                        unique_files: list[tuple[Path, str]] = []
                        for image_path in image_paths:
                            key = str(image_path.resolve()).lower()
                            if key in sent_for_chat:
                                continue
                            sent_for_chat.add(key)
                            unique_files.append((image_path, "image"))

                        for html_path in html_paths:
                            key = str(html_path.resolve()).lower()
                            if key in sent_for_chat:
                                continue
                            sent_for_chat.add(key)
                            unique_files.append((html_path, "html"))

                        for file_path, file_kind in unique_files:
                            try:
                                _send_document(
                                    client,
                                    base_url,
                                    token,
                                    chat_id,
                                    file_path,
                                    caption=f"[bridge] {file_kind}: {file_path.name}",
                                )
                            except Exception as send_file_error:
                                _send_message(
                                    client,
                                    base_url,
                                    token,
                                    chat_id,
                                    f"[bridge] failed to send {file_kind} {file_path.name}: {send_file_error}",
                                )
                    else:
                        _send_message(client, base_url, token, chat_id, "[bridge] no assistant message received")

            except Exception as error:  # pragma: no cover - long-running loop safeguard
                print(f"bridge loop error: {error}", flush=True)
                time.sleep(1.0)


if __name__ == "__main__":
    main()
