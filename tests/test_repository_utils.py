from sqlalchemy.exc import IntegrityError

from telegram_bot_new.db.repository import (
    _is_active_run_unique_conflict,
    _is_active_session_unique_conflict,
    _split_sql_statements,
)


def test_split_sql_statements_handles_comments_and_blanks() -> None:
    sql = """
    -- comment
    CREATE TABLE a (id INT);

    CREATE INDEX idx_a_id
      ON a (id);
    """

    statements = _split_sql_statements(sql)

    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE a")
    assert "CREATE INDEX idx_a_id" in statements[1]


def _mk_integrity_error(message: str) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, Exception(message))


def test_is_active_run_unique_conflict_detects_partial_index_name() -> None:
    error = _mk_integrity_error("duplicate key value violates unique constraint \"uq_cli_run_jobs_bot_chat_active\"")
    assert _is_active_run_unique_conflict(error) is True


def test_is_active_run_unique_conflict_ignores_fk_violation() -> None:
    error = _mk_integrity_error("insert or update on table \"cli_run_jobs\" violates foreign key constraint \"cli_run_jobs_turn_id_fkey\"")
    assert _is_active_run_unique_conflict(error) is False


def test_is_active_session_unique_conflict_detects_partial_index_name() -> None:
    error = _mk_integrity_error("duplicate key value violates unique constraint \"uq_sessions_bot_chat_active\"")
    assert _is_active_session_unique_conflict(error) is True


def test_is_active_session_unique_conflict_ignores_other_constraint() -> None:
    error = _mk_integrity_error("insert or update on table \"sessions\" violates foreign key constraint \"sessions_bot_id_fkey\"")
    assert _is_active_session_unique_conflict(error) is False
