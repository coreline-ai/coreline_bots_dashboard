from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from telegram_bot_new.settings import GlobalSettings, get_global_settings, load_bots_config

EVENT_LINE_RE = re.compile(r"^\[(\d+|~)\]\[(\d{2}:\d{2}:\d{2})\]\[([a-z_]+)\]\s?(.*)$", re.IGNORECASE)
SUPPORTED_AGENTS = ("codex", "gemini", "claude", "echo")


def mask_token(token: str) -> str:
    if len(token) <= 10:
        return token
    return f"{token[:4]}...{token[-4:]}"


def build_bot_catalog(
    *,
    bots_config_path: str | Path,
    embedded_host: str,
    embedded_base_port: int,
) -> list[dict[str, Any]]:
    config_path = Path(bots_config_path).expanduser().resolve()
    if not config_path.exists():
        return []
    try:
        settings = get_global_settings()
    except Exception:
        settings = GlobalSettings.model_validate({"DATABASE_URL": "postgresql+asyncpg://localhost/mock"})
    try:
        bots = load_bots_config(config_path, settings, allow_env_fallback=False)
    except Exception:
        return []

    embedded_index = 0
    rows: list[dict[str, Any]] = []
    for bot in bots:
        embedded_url: str | None = None
        if bot.mode == "embedded":
            embedded_url = f"http://{embedded_host}:{embedded_base_port + embedded_index}"
            embedded_index += 1

        rows.append(
            {
                "bot_id": str(bot.bot_id),
                "name": str(bot.name),
                "mode": bot.mode,
                "token": bot.telegram_token,
                "token_masked": mask_token(bot.telegram_token),
                "default_adapter": bot.adapter,
                "default_models": {
                    "codex": bot.codex.model,
                    "gemini": bot.gemini.model,
                    "claude": bot.claude.model,
                },
                "embedded_url": embedded_url,
                "webhook": {
                    "path_secret": bot.webhook.path_secret,
                    "secret_token": bot.webhook.secret_token,
                    "public_url": bot.webhook.public_url,
                },
            }
        )
    return rows


def create_dynamic_embedded_bot(
    *,
    bots_config_path: str | Path,
    adapter: str = "codex",
    bot_id: str | None = None,
    token: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    config_path = Path(bots_config_path).expanduser().resolve()
    raw = _read_bots_file_raw(config_path)
    bots = list(raw.get("bots") or [])

    used_bot_ids = {str(item.get("bot_id") or "").strip() for item in bots if isinstance(item, dict)}
    used_tokens = {str(item.get("telegram_token") or "").strip() for item in bots if isinstance(item, dict)}

    resolved_bot_id = _resolve_unique_text(
        preferred=(bot_id or "").strip(),
        used=used_bot_ids,
        pattern_prefix="bot-",
    )
    resolved_token = _resolve_unique_text(
        preferred=(token or "").strip(),
        used=used_tokens,
        pattern_prefix="mock_token_",
    )
    resolved_name = (name or "").strip() or _build_default_name(resolved_bot_id)

    entry = {
        "bot_id": resolved_bot_id,
        "name": resolved_name,
        "mode": "embedded",
        "telegram_token": resolved_token,
        "adapter": adapter if adapter in SUPPORTED_AGENTS else "codex",
        "webhook": {
            "path_secret": f"{resolved_bot_id}-path",
            "secret_token": f"{resolved_bot_id}-secret",
        },
    }
    bots.append(entry)
    raw["bots"] = bots
    _write_bots_file_raw(config_path, raw)

    return entry


def delete_bot_from_catalog(*, bots_config_path: str | Path, bot_id: str) -> bool:
    target = str(bot_id or "").strip()
    if not target:
        return False

    config_path = Path(bots_config_path).expanduser().resolve()
    raw = _read_bots_file_raw(config_path)
    bots = list(raw.get("bots") or [])
    next_bots: list[dict[str, Any]] = []
    removed = False
    for item in bots:
        if not isinstance(item, dict):
            continue
        current_id = str(item.get("bot_id") or "").strip()
        if current_id == target:
            removed = True
            continue
        next_bots.append(item)

    if not removed:
        return False

    raw["bots"] = next_bots
    _write_bots_file_raw(config_path, raw)
    return True


def _read_bots_file_raw(path: Path) -> dict[str, Any]:
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            bots = loaded.get("bots")
            if not isinstance(bots, list):
                loaded["bots"] = []
            return loaded
    return {"bots": []}


def _write_bots_file_raw(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(serialized, encoding="utf-8")
    tmp_path.replace(path)


def _resolve_unique_text(*, preferred: str, used: set[str], pattern_prefix: str) -> str:
    candidate = preferred.strip()
    if candidate and candidate not in used:
        return candidate

    index = 1
    while True:
        generated = f"{pattern_prefix}{index}"
        if generated not in used:
            return generated
        index += 1


def _build_default_name(bot_id: str) -> str:
    numeric = re.search(r"(\d+)$", bot_id)
    if numeric:
        return f"Bot {numeric.group(1)}"
    return bot_id


def infer_session_view_from_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "current_agent": "unknown",
        "session_id": None,
        "thread_id": None,
        "run_status": "idle",
        "summary_preview": None,
    }
    if not messages:
        return result

    for message in reversed(messages):
        text = str(message.get("text") or "")
        if not text:
            continue

        if result["session_id"] is None:
            match = re.search(r"(?:^|\n)session=([^\s\n]+)", text, flags=re.IGNORECASE)
            if match:
                result["session_id"] = match.group(1).strip()

        if result["thread_id"] is None:
            match = re.search(r"(?:^|\n)thread=([^\s\n]+)", text, flags=re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
                result["thread_id"] = None if raw == "none" else raw
            else:
                event_thread = re.search(
                    r"\[thread_started\]\s+.*?\"thread_id\"\s*:\s*\"([^\"]+)\"",
                    text,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if event_thread:
                    result["thread_id"] = event_thread.group(1).strip()

        if result["summary_preview"] is None:
            match = re.search(r"(?:^|\n)summary=(.+)", text, flags=re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
                result["summary_preview"] = None if raw == "none" else raw

        if result["current_agent"] == "unknown":
            queued = re.search(r"\bagent=(codex|gemini|claude)\b", text, flags=re.IGNORECASE)
            if queued:
                result["current_agent"] = queued.group(1).lower()
            else:
                status = re.search(r"(?:^|\n)adapter=(codex|gemini|claude)\b", text, flags=re.IGNORECASE)
                if status:
                    result["current_agent"] = status.group(1).lower()
                else:
                    switched = re.search(
                        r"mode switched:\s*(?:codex|gemini|claude)\s*->\s*(codex|gemini|claude)\b",
                        text,
                        flags=re.IGNORECASE,
                    )
                    if switched:
                        result["current_agent"] = switched.group(1).lower()

    result["run_status"] = _infer_latest_run_status(messages)

    return result


def classify_last_error_tag(messages: list[dict[str, Any]]) -> str:
    # Recent-run 기준: 최신 run이 정상 완료된 경우 과거 에러는 무시한다.
    for raw_line in _iter_message_lines_latest_first(messages):
        line = raw_line.strip()
        if not line:
            continue
        event_match = EVENT_LINE_RE.match(line)
        if event_match:
            event_type = event_match.group(3).lower()
            body = event_match.group(4).strip()
            if event_type == "turn_completed":
                return _classify_error_text(body) if _turn_completed_is_error(body) else "unknown"
            if event_type == "delivery_error":
                return "delivery_error"
            if event_type == "error":
                return _classify_error_text(body)
            continue

        # non-event line fallback (some bridges emit plain error text)
        classified = _classify_error_text(line)
        if classified != "unknown":
            return classified
    return "unknown"


def _iter_message_lines_latest_first(messages: list[dict[str, Any]]):
    for message in reversed(messages):
        text = str(message.get("text") or "")
        if not text:
            continue
        for line in reversed(text.splitlines()):
            yield line


def _turn_completed_is_error(body: str) -> bool:
    lowered = body.lower()
    if not lowered:
        return False
    # JSON payload, e.g. {"status":"error"} or {"status":"failed"}
    if re.search(r'"status"\s*:\s*"(error|failed|timeout)"', lowered):
        return True
    # plain form payload, e.g. status=error
    if re.search(r"\bstatus\s*=\s*(error|failed|timeout)\b", lowered):
        return True
    return False


def _classify_error_text(text: str) -> str:
    lowered = text.lower()
    if "executable not found" in lowered or "install cli" in lowered or "binary missing" in lowered:
        return "binary_missing"
    if "run is active" in lowered or "already active" in lowered or "/stop first" in lowered:
        return "active_run"
    if "invalid json" in lowered or "json decode" in lowered or "parse error" in lowered:
        return "parse_error"
    if "[delivery_error]" in lowered or "failed to send telegram message" in lowered:
        return "delivery_error"
    # Avoid false positives from path names like timeoutManager.js.
    timeout_signal = (
        "timed out" in lowered
        or "timeout exceeded" in lowered
        or "timeout reached" in lowered
        or ("timeout" in lowered and ("error" in lowered or "failed" in lowered or "exceed" in lowered))
    )
    if timeout_signal:
        return "timeout"
    if "[error]" in lowered:
        return "unknown"
    return "unknown"


def _infer_latest_run_status(messages: list[dict[str, Any]]) -> str:
    """
    최신 이벤트 기준 상태 계산.
    오래된 [error]가 최신 turn_completed(성공)를 덮어쓰지 않도록,
    최신 라인부터 역순으로 첫 run-significant 이벤트를 상태로 채택한다.
    """
    for raw_line in _iter_message_lines_latest_first(messages):
        line = raw_line.strip()
        if not line:
            continue

        event_match = EVENT_LINE_RE.match(line)
        if event_match:
            event_type = event_match.group(3).lower()
            body = event_match.group(4).strip()

            if event_type in {"error", "delivery_error"}:
                return "error"
            if event_type == "turn_completed":
                return "error" if _turn_completed_is_error(body) else "completed"
            if event_type in {"turn_started", "reasoning", "command_started", "assistant_message"}:
                return "running"
            if event_type == "thread_started":
                return "queued"
            continue

        lowered = line.lower()
        if "queued turn:" in lowered:
            return "queued"
        if "a run is already active" in lowered or "run is active" in lowered:
            return "running"

    return "idle"


def compact_threads(threads: list[dict[str, Any]], *, selected_chat_id: int | None) -> list[dict[str, Any]]:
    rows = [
        {
            "chat_id": row.get("chat_id"),
            "message_count": int(row.get("message_count") or 0),
            "webhook_enabled": bool(row.get("webhook_enabled")),
            "last_updated_at": int(row.get("last_updated_at") or 0),
        }
        for row in threads
    ]

    def _sort_key(item: dict[str, Any]) -> tuple[int, int]:
        selected = int(str(item.get("chat_id")) == str(selected_chat_id)) if selected_chat_id is not None else 0
        return (selected, int(item.get("last_updated_at") or 0))

    rows.sort(key=_sort_key, reverse=True)
    return rows[:10]


async def fetch_embedded_runtime(embedded_url: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not embedded_url:
        return (
            {
                "bot": {
                    "ok": False,
                    "status_code": None,
                    "latency_ms": None,
                    "error": "gateway mode: no dedicated embedded health endpoint",
                }
            },
            None,
        )

    started = time.perf_counter()
    timeout = httpx.Timeout(2.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            health_response = await client.get(f"{embedded_url}/healthz")
            latency_ms = int((time.perf_counter() - started) * 1000)
            if health_response.status_code < 200 or health_response.status_code >= 300:
                return (
                    {
                        "bot": {
                            "ok": False,
                            "status_code": health_response.status_code,
                            "latency_ms": latency_ms,
                            "error": f"healthz status={health_response.status_code}",
                        }
                    },
                    None,
                )
            metrics_response = await client.get(f"{embedded_url}/metrics")
            metrics_payload: dict[str, Any] | None = None
            if metrics_response.status_code == 200:
                metrics_payload = metrics_response.json()
            return (
                {
                    "bot": {
                        "ok": True,
                        "status_code": health_response.status_code,
                        "latency_ms": latency_ms,
                        "error": None,
                    }
                },
                metrics_payload,
            )
    except Exception as error:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return (
            {
                "bot": {
                    "ok": False,
                    "status_code": None,
                    "latency_ms": latency_ms,
                    "error": str(error),
                }
            },
            None,
        )


def extract_runtime_metrics(metrics_payload: dict[str, Any] | None) -> dict[str, Any]:
    runtime_counters = metrics_payload.get("runtime_counters", {}) if isinstance(metrics_payload, dict) else {}
    in_flight_runs = metrics_payload.get("in_flight_runs") if isinstance(metrics_payload, dict) else None
    return {
        "in_flight_runs": int(in_flight_runs) if isinstance(in_flight_runs, int) else None,
        "worker_heartbeat": {
            "run_worker": (
                int(runtime_counters["worker_heartbeat.run_worker"])
                if isinstance(runtime_counters.get("worker_heartbeat.run_worker"), int)
                else None
            ),
            "update_worker": (
                int(runtime_counters["worker_heartbeat.update_worker"])
                if isinstance(runtime_counters.get("worker_heartbeat.update_worker"), int)
                else None
            ),
        },
    }
