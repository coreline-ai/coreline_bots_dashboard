from pathlib import Path

import pytest

from telegram_bot_new.settings import GlobalSettings, load_bots_config, resolve_telegram_api_base_url


def test_load_bots_config_token_only_file(tmp_path: Path) -> None:
    config = tmp_path / "bots.yaml"
    config.write_text('bots:\n  - telegram_token: "123:abc"\n', encoding="utf-8")

    settings = GlobalSettings(_env_file=None, DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db")
    bots = load_bots_config(config, settings)

    assert len(bots) == 1
    assert bots[0].bot_id == "bot-1"
    assert bots[0].name == "Bot 1"
    assert bots[0].telegram_token == "123:abc"
    assert bots[0].ingest_mode == "polling"
    assert bots[0].codex.sandbox == "workspace-write"


def test_load_bots_config_falls_back_to_env_token(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"

    settings = GlobalSettings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
        TELEGRAM_BOT_TOKEN="999:xyz",
    )
    bots = load_bots_config(missing, settings)

    assert len(bots) == 1
    assert bots[0].telegram_token == "999:xyz"
    assert bots[0].bot_id == "bot-1"
    assert bots[0].mode == "embedded"


def test_placeholder_token_requires_env_fallback(tmp_path: Path) -> None:
    config = tmp_path / "bots.yaml"
    config.write_text("bots:\n  - telegram_token: TELEGRAM_BOT_TOKEN\n", encoding="utf-8")

    settings = GlobalSettings(_env_file=None, DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db")
    with pytest.raises(ValueError):
        load_bots_config(config, settings)


def test_placeholder_token_uses_virtual_token_for_mock_base(tmp_path: Path) -> None:
    config = tmp_path / "bots.yaml"
    config.write_text(
        "bots:\n"
        "  - telegram_token: TELEGRAM_BOT_TOKEN\n"
        "    telegram_api_base_url: http://127.0.0.1:9081\n",
        encoding="utf-8",
    )

    settings = GlobalSettings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
        TELEGRAM_VIRTUAL_TOKEN="virtual_tok_1",
    )
    bots = load_bots_config(config, settings)
    assert bots[0].telegram_token == "virtual_tok_1"


def test_env_only_mode_uses_virtual_token_for_mock_base(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    settings = GlobalSettings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db",
        TELEGRAM_API_BASE_URL="http://127.0.0.1:9081",
        TELEGRAM_VIRTUAL_TOKEN="virtual_tok_2",
    )
    bots = load_bots_config(missing, settings)
    assert bots[0].telegram_token == "virtual_tok_2"


def test_resolve_telegram_api_base_url_prefers_bot_override(tmp_path: Path) -> None:
    config = tmp_path / "bots.yaml"
    config.write_text(
        'bots:\n'
        '  - telegram_token: "123:abc"\n'
        '    telegram_api_base_url: "http://127.0.0.1:9081"\n',
        encoding="utf-8",
    )
    settings = GlobalSettings(_env_file=None, DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db")
    bots = load_bots_config(config, settings)
    assert resolve_telegram_api_base_url(bots[0], settings) == "http://127.0.0.1:9081"


def test_load_bots_config_parses_provider_models(tmp_path: Path) -> None:
    config = tmp_path / "bots.yaml"
    config.write_text(
        "bots:\n"
        "  - telegram_token: '123:abc'\n"
        "    adapter: gemini\n"
        "    gemini:\n"
        "      model: gemini-2.5-pro\n"
        "    claude:\n"
        "      model: claude-sonnet-4-5\n",
        encoding="utf-8",
    )
    settings = GlobalSettings(_env_file=None, DATABASE_URL="postgresql+asyncpg://u:p@127.0.0.1:5432/db")

    bots = load_bots_config(config, settings)

    assert len(bots) == 1
    assert bots[0].adapter == "gemini"
    assert bots[0].gemini.model == "gemini-2.5-pro"
    assert bots[0].claude.model == "claude-sonnet-4-5"
    assert bots[0].codex.model is None
