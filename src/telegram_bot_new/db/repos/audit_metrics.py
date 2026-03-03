from __future__ import annotations

from uuid import uuid4

from sqlalchemy import and_, func, select, text

from telegram_bot_new.db.models import AuditLog, CliRunJob, RuntimeMetricCounter, TelegramUpdate, TelegramUpdateJob


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


async def list_audit_logs(
    self,
    *,
    bot_id: str,
    chat_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    resolved_limit = max(1, min(int(limit), 500))
    async with self._session_factory() as session:
        query = select(AuditLog).where(AuditLog.bot_id == bot_id)
        if chat_id is not None:
            query = query.where(AuditLog.chat_id == chat_id)
        query = query.order_by(AuditLog.created_at.desc()).limit(resolved_limit)
        rows = (await session.execute(query)).scalars().all()
    return [
        {
            "id": str(row.id),
            "bot_id": str(row.bot_id),
            "chat_id": str(row.chat_id) if row.chat_id is not None else None,
            "session_id": str(row.session_id) if row.session_id is not None else None,
            "action": str(row.action),
            "result": str(row.result),
            "detail_json": row.detail_json,
            "created_at": int(row.created_at),
        }
        for row in rows
    ]


async def append_audit_log(
    self,
    *,
    bot_id: str,
    chat_id: str | None,
    session_id: str | None,
    action: str,
    result: str,
    detail_json: str | None,
    now: int,
) -> None:
    async with self._session_factory() as session:
        session.add(
            AuditLog(
                id=str(uuid4()),
                bot_id=bot_id,
                chat_id=chat_id,
                session_id=session_id,
                action=action[:64],
                result=result[:32],
                detail_json=detail_json[:4000] if isinstance(detail_json, str) else None,
                created_at=now,
            )
        )
        await session.commit()
