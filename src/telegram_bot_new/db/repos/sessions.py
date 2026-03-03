from __future__ import annotations

from uuid import uuid4

from sqlalchemy import and_, case, select, update
from sqlalchemy.exc import IntegrityError

from telegram_bot_new.db.models import Session, SessionSummary


async def get_latest_session(self, *, bot_id: str, chat_id: str) -> Session | None:
    async with self._session_factory() as session:
        result = await session.execute(
            select(Session)
            .where(and_(Session.bot_id == bot_id, Session.chat_id == chat_id))
            .order_by(
                case((Session.status == "active", 0), else_=1),
                Session.updated_at.desc(),
                Session.created_at.desc(),
                Session.session_id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_active_session(self, *, bot_id: str, chat_id: str) -> Session | None:
    async with self._session_factory() as session:
        result = await session.execute(
            select(Session)
            .where(and_(Session.bot_id == bot_id, Session.chat_id == chat_id, Session.status == "active"))
            .order_by(Session.updated_at.desc(), Session.created_at.desc(), Session.session_id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_or_create_active_session(
    self,
    *,
    bot_id: str,
    chat_id: str,
    adapter_name: str,
    adapter_model: str | None,
    active_skill: str | None = None,
    project_root: str | None = None,
    unsafe_until: int | None = None,
    now: int,
) -> SessionView:
    from telegram_bot_new.db.repository import SessionView, _is_active_session_unique_conflict

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
                adapter_model=adapter_model,
                active_skill=active_skill,
                project_root=project_root,
                unsafe_until=unsafe_until,
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
            adapter_model=found.adapter_model,
            active_skill=found.active_skill,
            project_root=found.project_root,
            unsafe_until=found.unsafe_until,
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


async def create_fresh_session(
    self,
    *,
    bot_id: str,
    chat_id: str,
    adapter_name: str,
    adapter_model: str | None,
    active_skill: str | None = None,
    project_root: str | None = None,
    unsafe_until: int | None = None,
    now: int,
) -> SessionView:
    from telegram_bot_new.db.repository import SessionView

    async with self._session_factory() as session:
        entity = Session(
            session_id=str(uuid4()),
            bot_id=bot_id,
            chat_id=chat_id,
            adapter_name=adapter_name,
            adapter_model=adapter_model,
            active_skill=active_skill,
            project_root=project_root,
            unsafe_until=unsafe_until,
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
            adapter_model=entity.adapter_model,
            active_skill=entity.active_skill,
            project_root=entity.project_root,
            unsafe_until=entity.unsafe_until,
            adapter_thread_id=entity.adapter_thread_id,
            status=entity.status,
            rolling_summary_md=entity.rolling_summary_md,
            last_turn_at=entity.last_turn_at,
        )


async def get_session_view(self, *, session_id: str) -> SessionView | None:
    from telegram_bot_new.db.repository import SessionView

    async with self._session_factory() as session:
        found = await session.get(Session, session_id)
        if found is None:
            return None
        return SessionView(
            session_id=found.session_id,
            bot_id=found.bot_id,
            chat_id=found.chat_id,
            adapter_name=found.adapter_name,
            adapter_model=found.adapter_model,
            active_skill=found.active_skill,
            project_root=found.project_root,
            unsafe_until=found.unsafe_until,
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


async def set_session_adapter(
    self,
    *,
    session_id: str,
    adapter_name: str,
    adapter_model: str | None,
    now: int,
) -> None:
    async with self._session_factory() as session:
        async with session.begin():
            target = await session.get(Session, session_id)
            if target is None:
                return
            await session.execute(
                update(Session)
                .where(
                    and_(
                        Session.bot_id == target.bot_id,
                        Session.chat_id == target.chat_id,
                        Session.status == "active",
                        Session.session_id != session_id,
                    )
                )
                .values(status="reset", adapter_thread_id=None, updated_at=now)
            )
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(
                    adapter_name=adapter_name,
                    adapter_model=adapter_model,
                    adapter_thread_id=None,
                    status="active",
                    updated_at=now,
                )
            )


async def set_session_skill(self, *, session_id: str, active_skill: str | None, now: int) -> None:
    async with self._session_factory() as session:
        async with session.begin():
            target = await session.get(Session, session_id)
            if target is None:
                return
            await session.execute(
                update(Session)
                .where(
                    and_(
                        Session.bot_id == target.bot_id,
                        Session.chat_id == target.chat_id,
                        Session.status == "active",
                        Session.session_id != session_id,
                    )
                )
                .values(status="reset", adapter_thread_id=None, updated_at=now)
            )
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(
                    active_skill=active_skill,
                    status="active",
                    updated_at=now,
                )
            )


async def set_session_model(self, *, session_id: str, adapter_model: str | None, now: int) -> None:
    async with self._session_factory() as session:
        async with session.begin():
            target = await session.get(Session, session_id)
            if target is None:
                return
            await session.execute(
                update(Session)
                .where(
                    and_(
                        Session.bot_id == target.bot_id,
                        Session.chat_id == target.chat_id,
                        Session.status == "active",
                        Session.session_id != session_id,
                    )
                )
                .values(status="reset", adapter_thread_id=None, updated_at=now)
            )
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(
                    adapter_model=adapter_model,
                    adapter_thread_id=None,
                    status="active",
                    updated_at=now,
                )
            )


async def set_session_project_root(self, *, session_id: str, project_root: str | None, now: int) -> None:
    async with self._session_factory() as session:
        async with session.begin():
            target = await session.get(Session, session_id)
            if target is None:
                return
            await session.execute(
                update(Session)
                .where(
                    and_(
                        Session.bot_id == target.bot_id,
                        Session.chat_id == target.chat_id,
                        Session.status == "active",
                        Session.session_id != session_id,
                    )
                )
                .values(status="reset", adapter_thread_id=None, updated_at=now)
            )
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(
                    project_root=project_root,
                    status="active",
                    updated_at=now,
                )
            )


async def set_session_unsafe_until(self, *, session_id: str, unsafe_until: int | None, now: int) -> None:
    async with self._session_factory() as session:
        async with session.begin():
            target = await session.get(Session, session_id)
            if target is None:
                return
            await session.execute(
                update(Session)
                .where(
                    and_(
                        Session.bot_id == target.bot_id,
                        Session.chat_id == target.chat_id,
                        Session.status == "active",
                        Session.session_id != session_id,
                    )
                )
                .values(status="reset", adapter_thread_id=None, updated_at=now)
            )
            await session.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(
                    unsafe_until=unsafe_until,
                    status="active",
                    updated_at=now,
                )
            )


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
