from __future__ import annotations

import os
from uuid import uuid4

import pytest

from telegram_bot_new.db.repository import Repository, create_repository

DEFAULT_TEST_POSTGRES_URL = "postgresql+asyncpg://tg:tg@127.0.0.1:54329/telegram_bot_new"


def _postgres_test_url() -> str:
    return os.getenv("TEST_POSTGRES_URL", DEFAULT_TEST_POSTGRES_URL)


async def _open_postgres_repo_or_skip() -> Repository:
    database_url = _postgres_test_url()
    repo = create_repository(database_url)
    try:
        await repo.create_schema()
    except Exception as exc:
        await repo.dispose()
        pytest.skip(
            f"Postgres integration requires reachable DB ({database_url}). "
            f"Bring up docker compose or set TEST_POSTGRES_URL. root_cause={exc}"
        )
    return repo


@pytest.mark.asyncio
async def test_postgres_create_schema_is_idempotent() -> None:
    repo = await _open_postgres_repo_or_skip()
    try:
        await repo.create_schema()
    finally:
        await repo.dispose()


@pytest.mark.asyncio
async def test_postgres_update_and_run_leasing_paths() -> None:
    repo = await _open_postgres_repo_or_skip()
    now = 1_700_100_000_000
    bot_id = f"bot-pg-{uuid4().hex[:8]}"
    chat_id = "2001"
    owner_user_id = int(uuid4().hex[:6], 16)
    update_id = int(uuid4().int % 1_000_000)

    try:
        await repo.upsert_bot(
            bot_id=bot_id,
            name="Postgres Bot",
            mode="embedded",
            owner_user_id=owner_user_id,
            adapter_name="codex",
            now=now,
        )
        await repo.insert_telegram_update(
            bot_id=bot_id,
            update_id=update_id,
            chat_id=chat_id,
            payload_json="{}",
            received_at=now + 1,
        )
        await repo.enqueue_telegram_update_job(bot_id=bot_id, update_id=update_id, available_at=now + 2)

        leased_update = await repo.lease_next_telegram_update_job(
            bot_id=bot_id,
            owner="pg-worker-update",
            now=now + 3,
            lease_duration_ms=5_000,
        )
        assert leased_update is not None
        assert leased_update.update_id == update_id

        session = await repo.get_or_create_active_session(
            bot_id=bot_id,
            chat_id=chat_id,
            adapter_name="codex",
            adapter_model="gpt-5",
            now=now + 4,
        )
        turn_id = await repo.create_turn_and_job(
            session_id=session.session_id,
            bot_id=bot_id,
            chat_id=chat_id,
            user_text="hello from postgres path",
            available_at=now + 5,
        )
        leased_run = await repo.lease_next_run_job(
            bot_id=bot_id,
            owner="pg-worker-run",
            now=now + 6,
            lease_duration_ms=10_000,
        )
        assert leased_run is not None
        assert leased_run.turn_id == turn_id
    finally:
        await repo.dispose()


@pytest.mark.asyncio
async def test_postgres_deferred_action_promotion_and_cli_events() -> None:
    repo = await _open_postgres_repo_or_skip()
    now = 1_700_100_010_000
    bot_id = f"bot-pg-{uuid4().hex[:8]}"
    chat_id = "2002"
    owner_user_id = int(uuid4().hex[:6], 16)

    try:
        await repo.upsert_bot(
            bot_id=bot_id,
            name="Postgres Bot",
            mode="embedded",
            owner_user_id=owner_user_id,
            adapter_name="gemini",
            now=now,
        )
        session = await repo.get_or_create_active_session(
            bot_id=bot_id,
            chat_id=chat_id,
            adapter_name="gemini",
            adapter_model="gemini-2.5-pro",
            now=now + 1,
        )
        origin_turn_id = await repo.create_turn_and_job(
            session_id=session.session_id,
            bot_id=bot_id,
            chat_id=chat_id,
            user_text="origin turn for deferred action",
            available_at=now + 2,
        )
        origin_leased_run = await repo.lease_next_run_job(
            bot_id=bot_id,
            owner="pg-worker-origin",
            now=now + 3,
            lease_duration_ms=10_000,
        )
        assert origin_leased_run is not None
        assert origin_leased_run.turn_id == origin_turn_id
        await repo.mark_run_in_flight(
            job_id=origin_leased_run.id,
            turn_id=origin_leased_run.turn_id,
            now=now + 4,
        )
        await repo.complete_run_job_and_turn(
            job_id=origin_leased_run.id,
            turn_id=origin_leased_run.turn_id,
            assistant_text="origin done",
            now=now + 5,
        )
        await repo.enqueue_deferred_button_action(
            bot_id=bot_id,
            chat_id=chat_id,
            session_id=session.session_id,
            action_type="retry",
            prompt_text="retry command",
            origin_turn_id=origin_turn_id,
            max_queue=3,
            now=now + 6,
        )

        promoted = await repo.promote_next_deferred_action(bot_id=bot_id, chat_id=chat_id, now=now + 7)
        assert promoted is not None
        assert promoted.action_type == "retry"

        leased_run = await repo.lease_next_run_job(
            bot_id=bot_id,
            owner="pg-worker-run",
            now=now + 8,
            lease_duration_ms=10_000,
        )
        assert leased_run is not None

        await repo.mark_run_in_flight(job_id=leased_run.id, turn_id=leased_run.turn_id, now=now + 9)
        await repo.append_cli_event(
            turn_id=leased_run.turn_id,
            bot_id=bot_id,
            seq=1,
            event_type="assistant_message",
            payload_json='{"text":"ok"}',
            now=now + 10,
        )
        await repo.complete_run_job_and_turn(
            job_id=leased_run.id,
            turn_id=leased_run.turn_id,
            assistant_text="done",
            now=now + 11,
        )

        event_count = await repo.get_turn_events_count(turn_id=leased_run.turn_id)
        turn = await repo.get_turn(turn_id=leased_run.turn_id)
        assert event_count == 1
        assert turn is not None
        assert turn.status == "completed"
    finally:
        await repo.dispose()
