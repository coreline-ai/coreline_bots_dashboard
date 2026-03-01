from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


BotMode = Literal["embedded", "gateway"]
AdapterName = Literal["codex", "gemini", "claude", "echo"]
IngestMode = Literal["webhook", "polling"]


class GlobalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: str = Field(alias="DATABASE_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    job_lease_ms: int = Field(default=30000, ge=1000, alias="JOB_LEASE_MS")
    worker_poll_interval_ms: int = Field(default=250, ge=50, alias="WORKER_POLL_INTERVAL_MS")
    supervisor_restart_max_backoff_sec: int = Field(default=30, ge=1, alias="SUPERVISOR_RESTART_MAX_BACKOFF_SEC")
    telegram_api_base_url: str = Field(default="https://api.telegram.org", alias="TELEGRAM_API_BASE_URL")
    telegram_virtual_token: str = Field(default="mock_token_1", alias="TELEGRAM_VIRTUAL_TOKEN")

    # Token-only bootstrap support
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_owner_user_id: int | None = Field(default=None, alias="TELEGRAM_OWNER_USER_ID")
    telegram_bot_id: str = Field(default="bot-1", alias="TELEGRAM_BOT_ID")
    telegram_bot_name: str = Field(default="Bot 1", alias="TELEGRAM_BOT_NAME")
    telegram_bot_mode: BotMode = Field(default="embedded", alias="TELEGRAM_BOT_MODE")
    telegram_webhook_public_url: str | None = Field(default=None, alias="TELEGRAM_WEBHOOK_PUBLIC_URL")
    telegram_webhook_path_secret: str | None = Field(default=None, alias="TELEGRAM_WEBHOOK_PATH_SECRET")
    telegram_webhook_secret_token: str | None = Field(default=None, alias="TELEGRAM_WEBHOOK_SECRET_TOKEN")
    strict_bot_db_isolation: bool = Field(default=False, alias="STRICT_BOT_DB_ISOLATION")


class WebhookConfig(BaseModel):
    path_secret: str | None = None
    secret_token: str | None = None
    public_url: str | None = None


class CodexConfig(BaseModel):
    model: str | None = None
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"


class GeminiConfig(BaseModel):
    model: str | None = None


class ClaudeConfig(BaseModel):
    model: str | None = None


class BotConfig(BaseModel):
    bot_id: str | None = None
    name: str | None = None
    mode: BotMode = "embedded"
    telegram_token: str
    owner_user_id: int | None = None
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    adapter: AdapterName = "gemini"
    codex: CodexConfig = Field(default_factory=CodexConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    database_url: str | None = None
    telegram_api_base_url: str | None = None

    @property
    def ingest_mode(self) -> IngestMode:
        return "webhook" if (self.webhook.public_url or "").strip() else "polling"


class BotsFile(BaseModel):
    bots: list[BotConfig]


@lru_cache(maxsize=1)
def get_global_settings() -> GlobalSettings:
    return GlobalSettings()


def load_bots_config(
    path: str | Path,
    settings: GlobalSettings | None = None,
    *,
    allow_env_fallback: bool = True,
) -> list[BotConfig]:
    resolved_settings = settings or get_global_settings()
    config_path = Path(path).expanduser().resolve()

    loaded_bots: list[BotConfig] = []
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if raw:
            try:
                parsed = BotsFile.model_validate(raw)
            except ValidationError as error:
                raise ValueError(f"invalid bots config at {config_path}: {error}") from error
            loaded_bots = parsed.bots

    if not loaded_bots and allow_env_fallback:
        env_bot = _build_env_bot(resolved_settings)
        if env_bot is None:
            raise FileNotFoundError(
                f"bots config not found at {config_path} and TELEGRAM_BOT_TOKEN is not set"
            )
        loaded_bots = [env_bot]

    if not loaded_bots:
        return []

    normalized = _normalize_bots(loaded_bots, resolved_settings)
    bot_ids = [b.bot_id for b in normalized]
    if len(bot_ids) != len(set(bot_ids)):
        raise ValueError("bots config contains duplicate bot_id values")
    tokens = [b.telegram_token for b in normalized]
    if len(tokens) != len(set(tokens)):
        raise ValueError("bots config contains duplicate telegram_token values")
    if resolved_settings.strict_bot_db_isolation and len(normalized) > 1:
        missing = [str(bot.bot_id) for bot in normalized if not str(bot.database_url or "").strip()]
        if missing:
            raise ValueError(
                "strict bot db isolation enabled but database_url missing for bots: "
                + ", ".join(missing)
            )

    return normalized


def resolve_bot_database_url(bot: BotConfig, global_settings: GlobalSettings) -> str:
    return bot.database_url or global_settings.database_url


def resolve_telegram_api_base_url(bot: BotConfig, global_settings: GlobalSettings) -> str:
    candidate = (bot.telegram_api_base_url or "").strip()
    if candidate:
        return candidate
    return global_settings.telegram_api_base_url


def _build_env_bot(settings: GlobalSettings) -> BotConfig | None:
    token = (settings.telegram_bot_token or "").strip()
    base_url = (settings.telegram_api_base_url or "").strip().lower()
    is_mock_base = base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")
    if not token and is_mock_base:
        token = settings.telegram_virtual_token.strip() or "mock_token_1"
    if not token:
        return None

    bot_id = settings.telegram_bot_id.strip() or "bot-1"
    webhook_path_secret = (settings.telegram_webhook_path_secret or "").strip() or f"{bot_id}-path"
    webhook_secret = (settings.telegram_webhook_secret_token or "").strip() or f"{bot_id}-secret"
    webhook_public_url = (settings.telegram_webhook_public_url or "").strip() or None

    return BotConfig(
        bot_id=bot_id,
        name=settings.telegram_bot_name.strip() or "Bot 1",
        mode=settings.telegram_bot_mode,
        telegram_token=token,
        owner_user_id=settings.telegram_owner_user_id,
        webhook=WebhookConfig(
            path_secret=webhook_path_secret,
            secret_token=webhook_secret,
            public_url=webhook_public_url,
        ),
    )


def _normalize_bots(bots: list[BotConfig], settings: GlobalSettings) -> list[BotConfig]:
    normalized: list[BotConfig] = []
    fallback_token = (settings.telegram_bot_token or "").strip() or None
    virtual_token = settings.telegram_virtual_token.strip() or "mock_token_1"

    for index, bot in enumerate(bots, start=1):
        base_url = ((bot.telegram_api_base_url or settings.telegram_api_base_url) or "").strip().lower()
        is_mock_base = base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")

        token = (bot.telegram_token or "").strip()
        if token == "TELEGRAM_BOT_TOKEN":
            token = fallback_token or (virtual_token if is_mock_base else "")
        elif token == "" and fallback_token:
            token = fallback_token
        elif token == "" and is_mock_base:
            token = virtual_token
        if not token:
            raise ValueError(f"bot[{index}] telegram_token is required")

        bot_id = (bot.bot_id or "").strip() or f"bot-{index}"
        name = (bot.name or "").strip() or f"Bot {index}"
        owner_user_id = bot.owner_user_id if bot.owner_user_id is not None else settings.telegram_owner_user_id

        webhook_public_url = (bot.webhook.public_url or "").strip() or None
        webhook_path_secret = (bot.webhook.path_secret or "").strip() or f"{bot_id}-path"
        webhook_secret_token = (bot.webhook.secret_token or "").strip() or f"{bot_id}-secret"

        normalized.append(
            BotConfig(
                bot_id=bot_id,
                name=name,
                mode=bot.mode,
                telegram_token=token,
                owner_user_id=owner_user_id,
                webhook=WebhookConfig(
                    path_secret=webhook_path_secret,
                    secret_token=webhook_secret_token,
                    public_url=webhook_public_url,
                ),
                adapter=bot.adapter,
                codex=bot.codex,
                gemini=bot.gemini,
                claude=bot.claude,
                database_url=bot.database_url,
                telegram_api_base_url=bot.telegram_api_base_url,
            )
        )

    return normalized
