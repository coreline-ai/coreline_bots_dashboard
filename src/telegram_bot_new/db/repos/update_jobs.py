from __future__ import annotations

from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from telegram_bot_new.db.models import TelegramUpdate, TelegramUpdateJob


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
    from telegram_bot_new.db.repository import LeasedTelegramUpdateJob

    is_postgres = self._engine.dialect.name == "postgresql"
    async with self._session_factory() as session:
        async with session.begin():
            claimable = and_(
                TelegramUpdateJob.bot_id == bot_id,
                TelegramUpdateJob.available_at <= now,
                or_(
                    TelegramUpdateJob.status == "queued",
                    and_(
                        TelegramUpdateJob.status == "leased",
                        TelegramUpdateJob.lease_expires_at.is_not(None),
                        TelegramUpdateJob.lease_expires_at < now,
                    ),
                ),
            )
            if is_postgres:
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
            else:
                row = (
                    await session.execute(
                        select(TelegramUpdateJob.id, TelegramUpdateJob.update_id)
                        .where(claimable)
                        .order_by(TelegramUpdateJob.available_at.asc(), TelegramUpdateJob.created_at.asc())
                        .limit(1)
                    )
                ).first()

            if row is None:
                return None

            lease_until = now + lease_duration_ms
            claimed = await session.execute(
                update(TelegramUpdateJob)
                .where(
                    and_(
                        TelegramUpdateJob.id == row.id,
                        claimable if not is_postgres else text("1=1"),
                    )
                )
                .values(
                    status="leased",
                    lease_owner=owner,
                    lease_expires_at=lease_until,
                    attempts=TelegramUpdateJob.attempts + 1,
                    updated_at=now,
                )
            )
            if not is_postgres and int(claimed.rowcount or 0) <= 0:
                return None

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


async def reset_telegram_ingest_state(self, *, bot_id: str) -> None:
    async with self._session_factory() as session:
        async with session.begin():
            await session.execute(
                delete(TelegramUpdateJob).where(TelegramUpdateJob.bot_id == bot_id)
            )
            await session.execute(
                delete(TelegramUpdate).where(TelegramUpdate.bot_id == bot_id)
            )
