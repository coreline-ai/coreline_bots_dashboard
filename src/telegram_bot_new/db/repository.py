from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import (
    ActionToken,
    Base,
    Bot,
    CliEvent,
    CliRunJob,
    DeferredButtonAction,
    RuntimeMetricCounter,
    Session,
    SessionSummary,
    TelegramUpdate,
    TelegramUpdateJob,
    Turn,
)


class ActiveRunExistsError(RuntimeError):
    pass


def _is_active_run_unique_conflict(error: IntegrityError) -> bool:
    message = str(error).lower()
    if "uq_cli_run_jobs_bot_chat_active" in message:
        return True
    if "duplicate key value violates unique constraint" in message and "cli_run_jobs" in message:
        return "bot_id" in message and "chat_id" in message
    return False


def _is_active_session_unique_conflict(error: IntegrityError) -> bool:
    message = str(error).lower()
    if "uq_sessions_bot_chat_active" in message:
        return True
    if "duplicate key value violates unique constraint" in message and "sessions" in message:
        return "bot_id" in message and "chat_id" in message
    return False


@dataclass(slots=True)
class LeasedTelegramUpdateJob:
    id: str
    update_id: int


@dataclass(slots=True)
class LeasedRunJob:
    id: str
    turn_id: str
    chat_id: str


@dataclass(slots=True)
class PromotedDeferredAction:
    action_id: str
    action_type: str
    turn_id: str


@dataclass(slots=True)
class SessionView:
    session_id: str
    bot_id: str
    chat_id: str
    adapter_name: str
    adapter_thread_id: str | None
    status: str
    rolling_summary_md: str
    last_turn_at: int | None


class Repository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine) -> None:
        self._session_factory = session_factory
        self._engine = engine

    async def create_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            migrations_dir = Path(__file__).resolve().parent / "migrations"
            if migrations_dir.exists() and migrations_dir.is_dir():
                for sql_path in sorted(migrations_dir.glob("*.sql")):
                    sql_text = sql_path.read_text(encoding="utf-8")
                    for statement in _split_sql_statements(sql_text):
                        await conn.execute(text(statement))

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def upsert_bot(self, *, bot_id: str, name: str, mode: str, owner_user_id: int, adapter_name: str, now: int) -> None:
        async with self._session_factory() as session:
            existing = await session.get(Bot, bot_id)
            if existing is None:
                session.add(
                    Bot(
                        bot_id=bot_id,
                        name=name,
                        mode=mode,
                        owner_user_id=owner_user_id,
                        adapter_name=adapter_name,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                existing.name = name
                existing.mode = mode
                existing.owner_user_id = owner_user_id
                existing.adapter_name = adapter_name
                existing.updated_at = now
            await session.commit()

    async def insert_telegram_update(
        self,
        *,
        bot_id: str,
        update_id: int,
        chat_id: str | None,
        payload_json: str,
        received_at: int,
    ) -> bool:
        async with self._session_factory() as session:
            session.add(
                TelegramUpdate(
                    bot_id=bot_id,
                    update_id=update_id,
                    chat_id=chat_id,
                    payload_json=payload_json,
                    received_at=received_at,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
        return True

    async def enqueue_telegram_update_job(self, *, bot_id: str, update_id: int, available_at: int) -> None:
        now = available_at
        async with self._session_factory() as session:
            session.add(
                TelegramUpdateJob(
                    id=str(uuid4()),
                    bot_id=bot_id,
                    update_id=update_id,
                    status="queued",
                    lease_owner=None,
                    lease_expires_at=None,
                    available_at=available_at,
                    attempts=0,
                    last_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

    async def lease_next_telegram_update_job(
        self,
        *,
        bot_id: str,
        owner: str,
        now: int,
        lease_duration_ms: int,
    ) -> LeasedTelegramUpdateJob | None:
        async with self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT id, update_id
                            FROM telegram_update_jobs
                            WHERE bot_id = :bot_id
                              AND available_at <= :now
                              AND (
                                status = 'queued'
                                OR (status = 'leased' AND lease_expires_at IS NOT NULL AND lease_expires_at < :now)
                              )
                            ORDER BY available_at ASC, created_at ASC
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                            """
                        ),
                        {"bot_id": bot_id, "now": now},
                    )
                ).first()

                if row is None:
                    return None

                lease_until = now + lease_duration_ms
                await session.execute(
                    update(TelegramUpdateJob)
                    .where(TelegramUpdateJob.id == row.id)
                    .values(
                        status="leased",
                        lease_owner=owner,
                        lease_expires_at=lease_until,
                        attempts=TelegramUpdateJob.attempts + 1,
                        updated_at=now,
                    )
                )

                return LeasedTelegramUpdateJob(id=str(row.id), update_id=int(row.update_id))

    async def renew_telegram_update_job_lease(self, *, job_id: str, now: int, lease_duration_ms: int) -> None:
        lease_until = now + lease_duration_ms
        async with self._session_factory() as session:
            await session.execute(
                update(TelegramUpdateJob)
                .where(and_(TelegramUpdateJob.id == job_id, TelegramUpdateJob.status == "leased"))
                .values(lease_expires_at=lease_until, updated_at=now)
            )
            await session.commit()

    async def complete_telegram_update_job(self, *, job_id: str, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(TelegramUpdateJob)
                .where(TelegramUpdateJob.id == job_id)
                .values(status="completed", lease_owner=None, lease_expires_at=None, updated_at=now)
            )
            await session.commit()

    async def fail_telegram_update_job(self, *, job_id: str, now: int, error: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(TelegramUpdateJob)
                .where(TelegramUpdateJob.id == job_id)
                .values(status="failed", lease_owner=None, lease_expires_at=None, last_error=error[:2000], updated_at=now)
            )
            await session.commit()

    async def get_telegram_update(self, *, bot_id: str, update_id: int) -> TelegramUpdate | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramUpdate).where(and_(TelegramUpdate.bot_id == bot_id, TelegramUpdate.update_id == update_id))
            )
            return result.scalar_one_or_none()

    async def get_max_telegram_update_id(self, *, bot_id: str) -> int | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.max(TelegramUpdate.update_id)).where(TelegramUpdate.bot_id == bot_id)
            )
            value = result.scalar_one_or_none()
            if value is None:
                return None
            return int(value)

    async def get_latest_session(self, *, bot_id: str, chat_id: str) -> Session | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Session)
                .where(and_(Session.bot_id == bot_id, Session.chat_id == chat_id))
                .order_by(Session.updated_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_or_create_active_session(self, *, bot_id: str, chat_id: str, adapter_name: str, now: int) -> SessionView:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Session)
                .where(and_(Session.bot_id == bot_id, Session.chat_id == chat_id, Session.status == "active"))
                .order_by(Session.updated_at.desc())
                .limit(1)
            )
            found = result.scalar_one_or_none()
            if found is None:
                found = Session(
                    session_id=str(uuid4()),
                    bot_id=bot_id,
                    chat_id=chat_id,
                    adapter_name=adapter_name,
                    adapter_thread_id=None,
                    status="active",
                    rolling_summary_md="",
                    last_turn_at=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(found)
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                if not _is_active_session_unique_conflict(error):
                    raise
                retry = await session.execute(
                    select(Session)
                    .where(and_(Session.bot_id == bot_id, Session.chat_id == chat_id, Session.status == "active"))
                    .order_by(Session.updated_at.desc())
                    .limit(1)
                )
                found = retry.scalar_one_or_none()
                if found is None:
                    raise
            await session.refresh(found)
            return SessionView(
                session_id=found.session_id,
                bot_id=found.bot_id,
                chat_id=found.chat_id,
                adapter_name=found.adapter_name,
                adapter_thread_id=found.adapter_thread_id,
                status=found.status,
                rolling_summary_md=found.rolling_summary_md,
                last_turn_at=found.last_turn_at,
            )

    async def reset_session(self, *, session_id: str, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(status="reset", adapter_thread_id=None, rolling_summary_md="", updated_at=now)
            )
            await session.commit()

    async def create_fresh_session(self, *, bot_id: str, chat_id: str, adapter_name: str, now: int) -> SessionView:
        async with self._session_factory() as session:
            entity = Session(
                session_id=str(uuid4()),
                bot_id=bot_id,
                chat_id=chat_id,
                adapter_name=adapter_name,
                adapter_thread_id=None,
                status="active",
                rolling_summary_md="",
                last_turn_at=None,
                created_at=now,
                updated_at=now,
            )
            async with session.begin():
                await session.execute(
                    update(Session)
                    .where(and_(Session.bot_id == bot_id, Session.chat_id == chat_id, Session.status == "active"))
                    .values(status="reset", adapter_thread_id=None, updated_at=now)
                )
                session.add(entity)
            await session.refresh(entity)
            return SessionView(
                session_id=entity.session_id,
                bot_id=entity.bot_id,
                chat_id=entity.chat_id,
                adapter_name=entity.adapter_name,
                adapter_thread_id=entity.adapter_thread_id,
                status=entity.status,
                rolling_summary_md=entity.rolling_summary_md,
                last_turn_at=entity.last_turn_at,
            )

    async def get_session_view(self, *, session_id: str) -> SessionView | None:
        async with self._session_factory() as session:
            found = await session.get(Session, session_id)
            if found is None:
                return None
            return SessionView(
                session_id=found.session_id,
                bot_id=found.bot_id,
                chat_id=found.chat_id,
                adapter_name=found.adapter_name,
                adapter_thread_id=found.adapter_thread_id,
                status=found.status,
                rolling_summary_md=found.rolling_summary_md,
                last_turn_at=found.last_turn_at,
            )

    async def set_session_thread_id(self, *, session_id: str, thread_id: str | None, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(adapter_thread_id=thread_id, updated_at=now)
            )
            await session.commit()

    async def set_session_adapter(self, *, session_id: str, adapter_name: str, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(
                    adapter_name=adapter_name,
                    adapter_thread_id=None,
                    status="active",
                    updated_at=now,
                )
            )
            await session.commit()

    async def upsert_session_summary(self, *, session_id: str, bot_id: str, turn_id: str, summary_md: str, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(rolling_summary_md=summary_md, last_turn_at=now, updated_at=now, status="active")
            )
            session.add(
                SessionSummary(
                    id=str(uuid4()),
                    session_id=session_id,
                    bot_id=bot_id,
                    turn_id=turn_id,
                    summary_md=summary_md,
                    created_at=now,
                )
            )
            await session.commit()

    async def create_turn_and_job(
        self,
        *,
        session_id: str,
        bot_id: str,
        chat_id: str,
        user_text: str,
        available_at: int,
    ) -> str:
        turn_id = str(uuid4())
        job_id = str(uuid4())
        now = available_at
        async with self._session_factory() as session:
            turn = Turn(
                turn_id=turn_id,
                session_id=session_id,
                bot_id=bot_id,
                chat_id=chat_id,
                user_text=user_text,
                assistant_text=None,
                status="queued",
                error_text=None,
                started_at=None,
                finished_at=None,
                created_at=now,
            )
            session.add(turn)
            session.add(
                CliRunJob(
                    id=job_id,
                    turn_id=turn_id,
                    bot_id=bot_id,
                    chat_id=chat_id,
                    status="queued",
                    lease_owner=None,
                    lease_expires_at=None,
                    available_at=available_at,
                    attempts=0,
                    last_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            try:
                # Ensure parent turn row is flushed before child run job row.
                # Without this, async flush ordering can trigger FK violations on Postgres.
                await session.flush([turn])
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                if _is_active_run_unique_conflict(error):
                    raise ActiveRunExistsError(f"active run already exists for bot={bot_id} chat={chat_id}") from error
                raise
        return turn_id

    async def lease_next_run_job(self, *, bot_id: str, owner: str, now: int, lease_duration_ms: int) -> LeasedRunJob | None:
        async with self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT id, turn_id, chat_id
                            FROM cli_run_jobs
                            WHERE bot_id = :bot_id
                              AND available_at <= :now
                              AND (
                                status = 'queued'
                                OR (
                                  status IN ('leased', 'in_flight')
                                  AND lease_expires_at IS NOT NULL
                                  AND lease_expires_at < :now
                                )
                              )
                            ORDER BY available_at ASC, created_at ASC
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                            """
                        ),
                        {"bot_id": bot_id, "now": now},
                    )
                ).first()

                if row is None:
                    return None

                lease_until = now + lease_duration_ms
                await session.execute(
                    update(CliRunJob)
                    .where(CliRunJob.id == row.id)
                    .values(
                        status="leased",
                        lease_owner=owner,
                        lease_expires_at=lease_until,
                        attempts=CliRunJob.attempts + 1,
                        updated_at=now,
                    )
                )
                await session.execute(
                    update(Turn)
                    .where(Turn.turn_id == row.turn_id)
                    .values(status="queued")
                )

                return LeasedRunJob(id=str(row.id), turn_id=str(row.turn_id), chat_id=str(row.chat_id))

    async def mark_run_in_flight(self, *, job_id: str, turn_id: str, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(CliRunJob)
                .where(CliRunJob.id == job_id)
                .values(status="in_flight", updated_at=now)
            )
            await session.execute(
                update(Turn)
                .where(Turn.turn_id == turn_id)
                .values(status="in_flight", started_at=now)
            )
            await session.commit()

    async def renew_run_job_lease(self, *, job_id: str, now: int, lease_duration_ms: int) -> None:
        lease_until = now + lease_duration_ms
        async with self._session_factory() as session:
            await session.execute(
                update(CliRunJob)
                .where(and_(CliRunJob.id == job_id, CliRunJob.status.in_(["leased", "in_flight"])))
                .values(lease_expires_at=lease_until, updated_at=now)
            )
            await session.commit()

    async def complete_run_job_and_turn(self, *, job_id: str, turn_id: str, assistant_text: str, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(CliRunJob)
                .where(CliRunJob.id == job_id)
                .values(status="completed", lease_owner=None, lease_expires_at=None, updated_at=now)
            )
            await session.execute(
                update(Turn)
                .where(Turn.turn_id == turn_id)
                .values(status="completed", assistant_text=assistant_text, finished_at=now)
            )
            await session.commit()

    async def fail_run_job_and_turn(self, *, job_id: str, turn_id: str, error_text: str, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(CliRunJob)
                .where(CliRunJob.id == job_id)
                .values(status="failed", lease_owner=None, lease_expires_at=None, last_error=error_text[:2000], updated_at=now)
            )
            await session.execute(
                update(Turn)
                .where(Turn.turn_id == turn_id)
                .values(status="failed", error_text=error_text[:4000], finished_at=now)
            )
            await session.commit()

    async def mark_run_job_cancelled(self, *, job_id: str, turn_id: str, now: int) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(CliRunJob)
                .where(CliRunJob.id == job_id)
                .values(status="cancelled", lease_owner=None, lease_expires_at=None, updated_at=now)
            )
            await session.execute(
                update(Turn)
                .where(Turn.turn_id == turn_id)
                .values(status="cancelled", finished_at=now)
            )
            await session.commit()

    async def cancel_active_turn(self, *, bot_id: str, chat_id: str, now: int) -> str | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(CliRunJob)
                    .where(
                        and_(
                            CliRunJob.bot_id == bot_id,
                            CliRunJob.chat_id == chat_id,
                            CliRunJob.status.in_(["queued", "leased", "in_flight"]),
                        )
                    )
                    .order_by(CliRunJob.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if row is None:
                return None

            await session.execute(
                update(CliRunJob)
                .where(CliRunJob.id == row.id)
                .values(status="cancelled", lease_owner=None, lease_expires_at=None, updated_at=now)
            )
            await session.execute(
                update(Turn)
                .where(Turn.turn_id == row.turn_id)
                .values(status="cancelled", finished_at=now)
            )
            await session.commit()
            return row.turn_id

    async def is_turn_cancelled(self, *, turn_id: str) -> bool:
        async with self._session_factory() as session:
            row = (
                await session.execute(select(Turn.status).where(Turn.turn_id == turn_id).limit(1))
            ).first()
            return bool(row and row[0] == "cancelled")

    async def append_cli_event(self, *, turn_id: str, bot_id: str, seq: int, event_type: str, payload_json: str, now: int) -> None:
        async with self._session_factory() as session:
            session.add(
                CliEvent(
                    turn_id=turn_id,
                    bot_id=bot_id,
                    seq=seq,
                    event_type=event_type,
                    payload_json=payload_json,
                    created_at=now,
                )
            )
            await session.commit()

    async def get_turn(self, *, turn_id: str) -> Turn | None:
        async with self._session_factory() as session:
            return await session.get(Turn, turn_id)

    async def get_latest_completed_turn_for_session(self, *, session_id: str) -> Turn | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Turn)
                .where(
                    and_(
                        Turn.session_id == session_id,
                        Turn.status == "completed",
                    )
                )
                .order_by(Turn.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def has_active_run(self, *, bot_id: str, chat_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count())
                .select_from(CliRunJob)
                .where(
                    and_(
                        CliRunJob.bot_id == bot_id,
                        CliRunJob.chat_id == chat_id,
                        CliRunJob.status.in_(["queued", "leased", "in_flight"]),
                    )
                )
            )
            return int(result.scalar_one()) > 0

    async def create_action_token(
        self,
        *,
        token: str,
        bot_id: str,
        chat_id: str,
        action: str,
        payload_json: str,
        expires_at: int,
        now: int,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                ActionToken(
                    token=token,
                    bot_id=bot_id,
                    chat_id=chat_id,
                    action=action,
                    payload_json=payload_json,
                    expires_at=expires_at,
                    consumed_at=None,
                    created_at=now,
                )
            )
            await session.commit()

    async def consume_action_token(
        self,
        *,
        token: str,
        bot_id: str,
        chat_id: str,
        now: int,
    ) -> ActionToken | None:
        async with self._session_factory() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        select(ActionToken)
                        .where(
                            and_(
                                ActionToken.token == token,
                                ActionToken.bot_id == bot_id,
                                ActionToken.chat_id == chat_id,
                                ActionToken.consumed_at.is_(None),
                                ActionToken.expires_at >= now,
                            )
                        )
                        .with_for_update()
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if row is None:
                    return None
                row.consumed_at = now
                return row

    async def enqueue_deferred_button_action(
        self,
        *,
        bot_id: str,
        chat_id: str,
        session_id: str,
        action_type: str,
        prompt_text: str,
        origin_turn_id: str,
        max_queue: int,
        now: int,
    ) -> str:
        action_id = str(uuid4())
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    DeferredButtonAction(
                        id=action_id,
                        bot_id=bot_id,
                        chat_id=chat_id,
                        session_id=session_id,
                        action_type=action_type,
                        prompt_text=prompt_text,
                        origin_turn_id=origin_turn_id,
                        status="queued",
                        created_at=now,
                        updated_at=now,
                    )
                )

                queued_ids = (
                    await session.execute(
                        select(DeferredButtonAction.id)
                        .where(
                            and_(
                                DeferredButtonAction.bot_id == bot_id,
                                DeferredButtonAction.chat_id == chat_id,
                                DeferredButtonAction.status == "queued",
                            )
                        )
                        .order_by(DeferredButtonAction.created_at.asc())
                    )
                ).scalars().all()

                overflow = len(queued_ids) - max(1, max_queue)
                if overflow > 0:
                    to_drop = queued_ids[:overflow]
                    await session.execute(
                        update(DeferredButtonAction)
                        .where(DeferredButtonAction.id.in_(to_drop))
                        .values(status="cancelled", updated_at=now)
                    )

        return action_id

    async def promote_next_deferred_action(
        self,
        *,
        bot_id: str,
        chat_id: str,
        now: int,
    ) -> PromotedDeferredAction | None:
        async with self._session_factory() as session:
            async with session.begin():
                active_count = (
                    await session.execute(
                        select(func.count())
                        .select_from(CliRunJob)
                        .where(
                            and_(
                                CliRunJob.bot_id == bot_id,
                                CliRunJob.chat_id == chat_id,
                                CliRunJob.status.in_(["queued", "leased", "in_flight"]),
                            )
                        )
                    )
                ).scalar_one()
                if int(active_count) > 0:
                    return None

                row = (
                    await session.execute(
                        select(DeferredButtonAction)
                        .where(
                            and_(
                                DeferredButtonAction.bot_id == bot_id,
                                DeferredButtonAction.chat_id == chat_id,
                                DeferredButtonAction.status == "queued",
                            )
                        )
                        .order_by(DeferredButtonAction.created_at.asc())
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                ).scalar_one_or_none()

                if row is None:
                    return None

                row.status = "promoted"
                row.updated_at = now

                turn_id = str(uuid4())
                job_id = str(uuid4())
                session.add(
                    Turn(
                        turn_id=turn_id,
                        session_id=row.session_id,
                        bot_id=bot_id,
                        chat_id=chat_id,
                        user_text=row.prompt_text,
                        assistant_text=None,
                        status="queued",
                        error_text=None,
                        started_at=None,
                        finished_at=None,
                        created_at=now,
                    )
                )
                session.add(
                    CliRunJob(
                        id=job_id,
                        turn_id=turn_id,
                        bot_id=bot_id,
                        chat_id=chat_id,
                        status="queued",
                        lease_owner=None,
                        lease_expires_at=None,
                        available_at=now,
                        attempts=0,
                        last_error=None,
                        created_at=now,
                        updated_at=now,
                    )
                )

                return PromotedDeferredAction(
                    action_id=row.id,
                    action_type=row.action_type,
                    turn_id=turn_id,
                )

    async def get_turn_events_count(self, *, turn_id: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(select(func.count()).select_from(CliEvent).where(CliEvent.turn_id == turn_id))
            return int(result.scalar_one())

    async def increment_runtime_metric(
        self,
        *,
        bot_id: str,
        metric_key: str,
        now: int,
        delta: int = 1,
    ) -> None:
        if delta == 0:
            return

        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO runtime_metric_counters (bot_id, metric_key, metric_value, updated_at)
                    VALUES (:bot_id, :metric_key, :delta, :now)
                    ON CONFLICT (bot_id, metric_key)
                    DO UPDATE
                    SET metric_value = runtime_metric_counters.metric_value + EXCLUDED.metric_value,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "bot_id": bot_id,
                    "metric_key": metric_key,
                    "delta": int(delta),
                    "now": now,
                },
            )
            await session.commit()

    async def get_metrics(self, *, bot_id: str | None = None) -> dict[str, Any]:
        async with self._session_factory() as session:
            update_q = select(func.count()).select_from(TelegramUpdateJob)
            run_q = select(func.count()).select_from(CliRunJob)
            in_flight_q = select(func.count()).select_from(CliRunJob).where(CliRunJob.status.in_(["leased", "in_flight"]))
            updates_total_q = select(func.count()).select_from(TelegramUpdate)
            update_status_q = select(TelegramUpdateJob.status, func.count()).select_from(TelegramUpdateJob)
            run_status_q = select(CliRunJob.status, func.count()).select_from(CliRunJob)
            runtime_counters_q = select(RuntimeMetricCounter.metric_key, RuntimeMetricCounter.metric_value).select_from(
                RuntimeMetricCounter
            )

            if bot_id is not None:
                update_q = update_q.where(TelegramUpdateJob.bot_id == bot_id)
                run_q = run_q.where(CliRunJob.bot_id == bot_id)
                in_flight_q = in_flight_q.where(CliRunJob.bot_id == bot_id)
                updates_total_q = updates_total_q.where(TelegramUpdate.bot_id == bot_id)
                update_status_q = update_status_q.where(TelegramUpdateJob.bot_id == bot_id)
                run_status_q = run_status_q.where(CliRunJob.bot_id == bot_id)
                runtime_counters_q = runtime_counters_q.where(RuntimeMetricCounter.bot_id == bot_id)

            update_status_q = update_status_q.group_by(TelegramUpdateJob.status)
            run_status_q = run_status_q.group_by(CliRunJob.status)

            updates_jobs = int((await session.execute(update_q)).scalar_one())
            run_jobs = int((await session.execute(run_q)).scalar_one())
            in_flight = int((await session.execute(in_flight_q)).scalar_one())
            updates_total = int((await session.execute(updates_total_q)).scalar_one())
            update_status_rows = (await session.execute(update_status_q)).all()
            run_status_rows = (await session.execute(run_status_q)).all()
            runtime_counter_rows = (await session.execute(runtime_counters_q)).all()

            return {
                "telegram_update_jobs": updates_jobs,
                "cli_run_jobs": run_jobs,
                "in_flight_runs": in_flight,
                "telegram_updates_total": updates_total,
                "telegram_update_jobs_by_status": {
                    str(row[0]): int(row[1]) for row in update_status_rows if isinstance(row[0], str)
                },
                "cli_run_jobs_by_status": {
                    str(row[0]): int(row[1]) for row in run_status_rows if isinstance(row[0], str)
                },
                "runtime_counters": {
                    str(row[0]): int(row[1]) for row in runtime_counter_rows if isinstance(row[0], str)
                },
            }


def create_repository(database_url: str) -> Repository:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return Repository(session_factory, engine)


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []

    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip()
            if statement.endswith(";"):
                statement = statement[:-1]
            if statement:
                statements.append(statement)
            current = []

    if current:
        statement = "\n".join(current).strip()
        if statement:
            statements.append(statement)

    return statements
