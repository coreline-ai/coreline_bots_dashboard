from __future__ import annotations

from pathlib import Path

import pytest

from telegram_bot_new.db.repository import create_repository


@pytest.mark.asyncio
async def test_sqlite_lease_paths_work_without_postgres_lock_sql(tmp_path: Path) -> None:
    db_path = tmp_path / "sqlite-lease.db"
    repo = create_repository(f"sqlite+aiosqlite:///{db_path}")
    now = 1_700_000_000_000

    try:
        await repo.create_schema()
        await repo.upsert_bot(
            bot_id="bot-sqlite",
            name="SQLite Bot",
            mode="embedded",
            owner_user_id=9001,
            adapter_name="gemini",
            now=now,
        )

        await repo.insert_telegram_update(
            bot_id="bot-sqlite",
            update_id=100,
            chat_id="1001",
            payload_json="{}",
            received_at=now,
        )
        await repo.enqueue_telegram_update_job(bot_id="bot-sqlite", update_id=100, available_at=now)
        leased_update = await repo.lease_next_telegram_update_job(
            bot_id="bot-sqlite",
            owner="worker-a",
            now=now + 1,
            lease_duration_ms=5_000,
        )
        assert leased_update is not None
        assert leased_update.update_id == 100

        session = await repo.get_or_create_active_session(
            bot_id="bot-sqlite",
            chat_id="1001",
            adapter_name="gemini",
            adapter_model="gemini-2.5-pro",
            now=now + 2,
        )
        turn_id = await repo.create_turn_and_job(
            session_id=session.session_id,
            bot_id="bot-sqlite",
            chat_id="1001",
            user_text="hello",
            available_at=now + 3,
        )
        leased_run = await repo.lease_next_run_job(
            bot_id="bot-sqlite",
            owner="worker-b",
            now=now + 4,
            lease_duration_ms=10_000,
        )
        assert leased_run is not None
        assert leased_run.turn_id == turn_id
    finally:
        await repo.dispose()


@pytest.mark.asyncio
async def test_sqlite_promote_deferred_action_without_skip_locked(tmp_path: Path) -> None:
    db_path = tmp_path / "sqlite-deferred.db"
    repo = create_repository(f"sqlite+aiosqlite:///{db_path}")
    now = 1_700_000_010_000

    try:
        await repo.create_schema()
        await repo.upsert_bot(
            bot_id="bot-sqlite",
            name="SQLite Bot",
            mode="embedded",
            owner_user_id=9001,
            adapter_name="codex",
            now=now,
        )
        session = await repo.get_or_create_active_session(
            bot_id="bot-sqlite",
            chat_id="1001",
            adapter_name="codex",
            adapter_model="gpt-5",
            now=now + 1,
        )

        await repo.enqueue_deferred_button_action(
            bot_id="bot-sqlite",
            chat_id="1001",
            session_id=session.session_id,
            action_type="retry",
            prompt_text="retry this",
            origin_turn_id="turn-origin",
            max_queue=3,
            now=now + 2,
        )

        promoted = await repo.promote_next_deferred_action(bot_id="bot-sqlite", chat_id="1001", now=now + 3)
        assert promoted is not None
        assert promoted.action_type == "retry"
    finally:
        await repo.dispose()


@pytest.mark.asyncio
async def test_sqlite_append_cli_event_assigns_id_when_schema_lacks_autoincrement(tmp_path: Path) -> None:
    db_path = tmp_path / "sqlite-events.db"
    repo = create_repository(f"sqlite+aiosqlite:///{db_path}")
    now = 1_700_000_020_000

    try:
        await repo.create_schema()
        await repo.upsert_bot(
            bot_id="bot-sqlite",
            name="SQLite Bot",
            mode="embedded",
            owner_user_id=9001,
            adapter_name="gemini",
            now=now,
        )
        session = await repo.get_or_create_active_session(
            bot_id="bot-sqlite",
            chat_id="1001",
            adapter_name="gemini",
            adapter_model="gemini-2.5-pro",
            now=now + 1,
        )
        turn_id = await repo.create_turn_and_job(
            session_id=session.session_id,
            bot_id="bot-sqlite",
            chat_id="1001",
            user_text="hello",
            available_at=now + 2,
        )

        await repo.append_cli_event(
            turn_id=turn_id,
            bot_id="bot-sqlite",
            seq=1,
            event_type="assistant_message",
            payload_json='{"text":"ok"}',
            now=now + 3,
        )
    finally:
        await repo.dispose()


@pytest.mark.asyncio
async def test_get_latest_session_prefers_active_when_reset_has_same_updated_at(tmp_path: Path) -> None:
    db_path = tmp_path / "sqlite-session-order.db"
    repo = create_repository(f"sqlite+aiosqlite:///{db_path}")
    now = 1_700_000_030_000

    try:
        await repo.create_schema()
        await repo.upsert_bot(
            bot_id="bot-sqlite",
            name="SQLite Bot",
            mode="embedded",
            owner_user_id=9001,
            adapter_name="gemini",
            now=now,
        )
        first = await repo.get_or_create_active_session(
            bot_id="bot-sqlite",
            chat_id="1001",
            adapter_name="claude",
            adapter_model="claude-sonnet-4-5",
            now=now + 1,
        )
        second = await repo.create_fresh_session(
            bot_id="bot-sqlite",
            chat_id="1001",
            adapter_name="gemini",
            adapter_model="gemini-2.5-flash",
            now=now + 2,
        )

        latest = await repo.get_latest_session(bot_id="bot-sqlite", chat_id="1001")
        active = await repo.get_active_session(bot_id="bot-sqlite", chat_id="1001")
        assert latest is not None
        assert active is not None
        assert latest.session_id == second.session_id
        assert latest.status == "active"
        assert active.session_id == second.session_id
        assert active.session_id != first.session_id
    finally:
        await repo.dispose()


@pytest.mark.asyncio
async def test_set_session_adapter_can_promote_reset_session_without_unique_conflict(tmp_path: Path) -> None:
    db_path = tmp_path / "sqlite-session-promote.db"
    repo = create_repository(f"sqlite+aiosqlite:///{db_path}")
    now = 1_700_000_040_000

    try:
        await repo.create_schema()
        await repo.upsert_bot(
            bot_id="bot-sqlite",
            name="SQLite Bot",
            mode="embedded",
            owner_user_id=9001,
            adapter_name="gemini",
            now=now,
        )
        first = await repo.get_or_create_active_session(
            bot_id="bot-sqlite",
            chat_id="1001",
            adapter_name="claude",
            adapter_model="claude-sonnet-4-5",
            now=now + 1,
        )
        second = await repo.create_fresh_session(
            bot_id="bot-sqlite",
            chat_id="1001",
            adapter_name="gemini",
            adapter_model="gemini-2.5-pro",
            now=now + 2,
        )

        await repo.set_session_adapter(
            session_id=first.session_id,
            adapter_name="gemini",
            adapter_model="gemini-2.5-flash",
            now=now + 3,
        )

        promoted = await repo.get_active_session(bot_id="bot-sqlite", chat_id="1001")
        demoted = await repo.get_session_view(session_id=second.session_id)
        assert promoted is not None
        assert promoted.session_id == first.session_id
        assert promoted.adapter_name == "gemini"
        assert promoted.adapter_model == "gemini-2.5-flash"
        assert demoted is not None
        assert demoted.status == "reset"
    finally:
        await repo.dispose()
