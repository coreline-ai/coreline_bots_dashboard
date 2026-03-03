from __future__ import annotations

from uuid import uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from telegram_bot_new.db.models import CliEvent, CliRunJob, DeferredButtonAction, Turn


async def create_turn_and_job(
    self,
    *,
    session_id: str,
    bot_id: str,
    chat_id: str,
    user_text: str,
    available_at: int,
) -> str:
    from telegram_bot_new.db.repository import ActiveRunExistsError, _is_active_run_unique_conflict

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
    from telegram_bot_new.db.repository import LeasedRunJob

    is_postgres = self._engine.dialect.name == "postgresql"
    async with self._session_factory() as session:
        async with session.begin():
            claimable = and_(
                CliRunJob.bot_id == bot_id,
                CliRunJob.available_at <= now,
                or_(
                    CliRunJob.status == "queued",
                    and_(
                        CliRunJob.status.in_(["leased", "in_flight"]),
                        CliRunJob.lease_expires_at.is_not(None),
                        CliRunJob.lease_expires_at < now,
                    ),
                ),
            )
            if is_postgres:
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
            else:
                row = (
                    await session.execute(
                        select(CliRunJob.id, CliRunJob.turn_id, CliRunJob.chat_id)
                        .where(claimable)
                        .order_by(CliRunJob.available_at.asc(), CliRunJob.created_at.asc())
                        .limit(1)
                    )
                ).first()

            if row is None:
                return None

            lease_until = now + lease_duration_ms
            claimed = await session.execute(
                update(CliRunJob)
                .where(
                    and_(
                        CliRunJob.id == row.id,
                        claimable if not is_postgres else text("1=1"),
                    )
                )
                .values(
                    status="leased",
                    lease_owner=owner,
                    lease_expires_at=lease_until,
                    attempts=CliRunJob.attempts + 1,
                    updated_at=now,
                )
            )
            if not is_postgres and int(claimed.rowcount or 0) <= 0:
                return None
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
        # SQLite may carry legacy cli_events schemas where `id` is not an
        # auto-incrementing INTEGER PRIMARY KEY. In that case, assign id
        # explicitly to keep event ingestion stable.
        if self._engine.dialect.name == "sqlite":
            for _ in range(3):
                next_id = int(
                    (
                        await session.execute(
                            select(func.coalesce(func.max(CliEvent.id), 0) + 1)
                        )
                    ).scalar_one()
                )
                session.add(
                    CliEvent(
                        id=next_id,
                        turn_id=turn_id,
                        bot_id=bot_id,
                        seq=seq,
                        event_type=event_type,
                        payload_json=payload_json,
                        created_at=now,
                    )
                )
                try:
                    await session.commit()
                    return
                except IntegrityError:
                    await session.rollback()
                    continue
            raise RuntimeError("failed to append cli event after retries")

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
    from telegram_bot_new.db.repository import PromotedDeferredAction

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
                    (
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
                    if self._engine.dialect.name == "postgresql"
                    else (
                        select(DeferredButtonAction)
                        .where(
                            and_(
                                DeferredButtonAction.bot_id == bot_id,
                                DeferredButtonAction.chat_id == chat_id,
                                DeferredButtonAction.status == "queued",
                            )
                        )
                        .order_by(DeferredButtonAction.created_at.asc())
                        .limit(1)
                    )
                )
            ).scalar_one_or_none()

            if row is None:
                return None

            row.status = "promoted"
            row.updated_at = now

            turn_id = str(uuid4())
            job_id = str(uuid4())
            turn = Turn(
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
            session.add(turn)
            # Keep parent->child flush ordering explicit for Postgres FK safety.
            await session.flush([turn])
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
