from __future__ import annotations

from telegram_bot_new.runtime_embedded import _resolve_worker_database_url
from telegram_bot_new.settings import BotConfig, GlobalSettings


def _settings() -> GlobalSettings:
    return GlobalSettings.model_validate({"DATABASE_URL": "sqlite+aiosqlite:////tmp/global.db"})


def test_gateway_worker_forces_global_database_url() -> None:
    bot = BotConfig(
        bot_id="bot-gw",
        mode="gateway",
        telegram_token="token-gw",
        database_url="sqlite+aiosqlite:////tmp/per-bot.db",
    )

    assert _resolve_worker_database_url(bot, _settings()) == "sqlite+aiosqlite:////tmp/global.db"


def test_embedded_worker_uses_bot_database_url_when_set() -> None:
    bot = BotConfig(
        bot_id="bot-embedded",
        mode="embedded",
        telegram_token="token-embedded",
        database_url="sqlite+aiosqlite:////tmp/embedded.db",
    )

    assert _resolve_worker_database_url(bot, _settings()) == "sqlite+aiosqlite:////tmp/embedded.db"
