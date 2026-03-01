from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Bot(Base):
    __tablename__ = "bots"

    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"

    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TelegramUpdateJob(Base):
    __tablename__ = "telegram_update_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    update_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    available_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("uq_telegram_update_jobs_bot_update", "bot_id", "update_id", unique=True),
    )


class Session(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    adapter_name: Mapped[str] = mapped_column(String(32), nullable=False)
    adapter_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    project_root: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    unsafe_until: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    adapter_thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rolling_summary_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_turn_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class Turn(Base):
    __tablename__ = "turns"

    turn_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_text: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class CliRunJob(Base):
    __tablename__ = "cli_run_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(64), ForeignKey("turns.turn_id", ondelete="CASCADE"), nullable=False, unique=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    available_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class CliEvent(Base):
    __tablename__ = "cli_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    turn_id: Mapped[str] = mapped_column(String(64), ForeignKey("turns.turn_id", ondelete="CASCADE"), nullable=False, index=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("uq_cli_events_turn_seq", "turn_id", "seq", unique=True),
    )


class SessionSummary(Base):
    __tablename__ = "session_summaries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    turn_id: Mapped[str] = mapped_column(String(64), ForeignKey("turns.turn_id", ondelete="CASCADE"), nullable=False, index=True)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ActionToken(Base):
    __tablename__ = "action_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    consumed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class DeferredButtonAction(Base):
    __tablename__ = "deferred_button_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    origin_turn_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("turns.turn_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RuntimeMetricCounter(Base):
    __tablename__ = "runtime_metric_counters"

    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    metric_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


Index("ix_sessions_bot_chat_updated", Session.bot_id, Session.chat_id, Session.updated_at.desc())
Index(
    "ix_deferred_button_actions_bot_chat_status_created",
    DeferredButtonAction.bot_id,
    DeferredButtonAction.chat_id,
    DeferredButtonAction.status,
    DeferredButtonAction.created_at,
)
Index("ix_runtime_metric_counters_bot_key", RuntimeMetricCounter.bot_id, RuntimeMetricCounter.metric_key)
Index("ix_audit_logs_bot_chat_created", AuditLog.bot_id, AuditLog.chat_id, AuditLog.created_at.desc())
