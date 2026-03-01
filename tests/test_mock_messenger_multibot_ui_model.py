from __future__ import annotations

from telegram_bot_new.mock_messenger.bot_catalog import (
    classify_last_error_tag,
    compact_threads,
    infer_session_view_from_messages,
)


def test_infer_session_view_from_messages() -> None:
    messages = [
        {"message_id": 1, "direction": "bot", "text": "Queued turn: abc\nsession=s-1\nagent=gemini"},
        {
            "message_id": 2,
            "direction": "bot",
            "text": "bot=bot-a\nadapter=gemini\nmodel=default\nproject=/tmp/myproj\nunsafe_until=1712345678901\nsession=s-1\nthread=t-1\nsummary=hello world",
        },
        {"message_id": 3, "direction": "bot", "text": "[1][12:00:00][turn_completed] {\"status\":\"ok\"}"},
    ]
    inferred = infer_session_view_from_messages(messages)
    assert inferred["current_agent"] == "gemini"
    assert inferred["current_model"] is None
    assert inferred["current_project"] == "/tmp/myproj"
    assert inferred["unsafe_until"] == 1712345678901
    assert inferred["session_id"] == "s-1"
    assert inferred["thread_id"] == "t-1"
    assert inferred["summary_preview"] == "hello world"
    assert inferred["run_status"] == "completed"


def test_classify_last_error_tag() -> None:
    assert classify_last_error_tag([{"text": "provider=gemini executable not found; install CLI"}]) == "binary_missing"
    assert classify_last_error_tag([{"text": "request timeout exceeded"}]) == "timeout"
    assert classify_last_error_tag([{"text": "A run is active. Use /stop first"}]) == "active_run"
    assert classify_last_error_tag([{"text": "invalid json payload"}]) == "parse_error"
    assert classify_last_error_tag([{"text": "[delivery_error] failed to send telegram message"}]) == "delivery_error"
    assert classify_last_error_tag([{"text": "plain message"}]) == "unknown"


def test_infer_session_view_ignores_stale_error_when_latest_run_completed() -> None:
    messages = [
        {"message_id": 1, "direction": "bot", "text": "[1][12:00:00][error] old failure"},
        {"message_id": 2, "direction": "bot", "text": "Queued turn: xyz\nsession=s-2\nagent=codex"},
        {"message_id": 3, "direction": "bot", "text": "[1][12:00:02][turn_completed] {\"status\":\"success\"}"},
    ]
    inferred = infer_session_view_from_messages(messages)
    assert inferred["run_status"] == "completed"


def test_infer_session_view_reads_thread_id_from_thread_started_event() -> None:
    messages = [
        {"message_id": 1, "direction": "bot", "text": "Queued turn: abc\nsession=s-3\nagent=codex"},
        {"message_id": 2, "direction": "bot", "text": "[1][12:00:01][thread_started] {\"thread_id\": \"t-xyz\"}"},
        {"message_id": 3, "direction": "bot", "text": "[2][12:00:02][turn_completed] {\"status\":\"success\"}"},
    ]
    inferred = infer_session_view_from_messages(messages)
    assert inferred["thread_id"] == "t-xyz"


def test_classify_last_error_tag_ignores_stale_timeout_path_strings() -> None:
    messages = [
        {"message_id": 1, "direction": "bot", "text": "[1][11:00:00][error] timeout reached (900s)"},
        {
            "message_id": 2,
            "direction": "bot",
            "text": "[1][11:05:00][turn_completed] {\"status\":\"success\"}\ntests/e2e/node_modules/playwright/lib/worker/timeoutManager.js",
        },
    ]
    assert classify_last_error_tag(messages) == "unknown"


def test_compact_threads_puts_selected_chat_first() -> None:
    rows = [
        {"chat_id": 3003, "message_count": 1, "webhook_enabled": False, "last_updated_at": 10},
        {"chat_id": 1001, "message_count": 5, "webhook_enabled": True, "last_updated_at": 5},
        {"chat_id": 2002, "message_count": 2, "webhook_enabled": False, "last_updated_at": 20},
    ]
    compact = compact_threads(rows, selected_chat_id=1001)
    assert compact[0]["chat_id"] == 1001
    assert len(compact) == 3


def test_infer_session_view_reads_non_default_model() -> None:
    messages = [
        {
            "message_id": 1,
            "direction": "bot",
            "text": "bot=bot-a\nadapter=codex\nmodel=gpt-5\nsession=s-9\nthread=t-9\nsummary=none",
        }
    ]
    inferred = infer_session_view_from_messages(messages)
    assert inferred["current_agent"] == "codex"
    assert inferred["current_model"] == "gpt-5"


def test_infer_session_view_reads_updated_project_and_unsafe_from_update_message() -> None:
    messages = [
        {"message_id": 1, "direction": "bot", "text": "project updated: default -> /Users/test/work-a"},
        {"message_id": 2, "direction": "bot", "text": "unsafe updated: off -> 1711111111111"},
    ]
    inferred = infer_session_view_from_messages(messages)
    assert inferred["current_project"] == "/Users/test/work-a"
    assert inferred["unsafe_until"] == 1711111111111
