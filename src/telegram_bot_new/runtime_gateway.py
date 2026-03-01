from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException

from telegram_bot_new.db.repository import create_repository
from telegram_bot_new.settings import BotConfig, GlobalSettings, resolve_telegram_api_base_url
from telegram_bot_new.telegram.api import extract_chat_id
from telegram_bot_new.telegram.client import TelegramApiError, TelegramClient

LOGGER = logging.getLogger(__name__)
GLOBAL_METRICS_BOT_ID = "__global__"


def _now_ms() -> int:
    return int(time.time() * 1000)


async def run_gateway_server(bots: list[BotConfig], global_settings: GlobalSettings, host: str, port: int) -> None:
    logging.basicConfig(level=getattr(logging, global_settings.log_level.upper(), logging.INFO))

    if not bots:
        raise ValueError("gateway mode requires at least one bot")

    repository = create_repository(global_settings.database_url)
    bot_map = {bot.bot_id: bot for bot in bots}

    async def _inc_metric(bot_id: str, metric_key: str) -> None:
        try:
            await repository.increment_runtime_metric(
                bot_id=bot_id,
                metric_key=metric_key,
                now=_now_ms(),
            )
        except Exception:
            LOGGER.exception("failed to increment runtime metric bot=%s metric=%s", bot_id, metric_key)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await repository.create_schema()
        for bot in bots:
            await repository.upsert_bot(
                bot_id=str(bot.bot_id),
                name=str(bot.name),
                mode=bot.mode,
                owner_user_id=bot.owner_user_id or 0,
                adapter_name=bot.adapter,
                now=_now_ms(),
            )
            if bot.ingest_mode == "webhook":
                async def _on_telegram_rate_limit(method: str, retry_after: int, *, _bot_id: str = str(bot.bot_id)) -> None:
                    await _inc_metric(_bot_id, "telegram_rate_limit_retry_total")
                    await _inc_metric(_bot_id, f"telegram_rate_limit_retry.{method}")

                client = TelegramClient(
                    bot.telegram_token,
                    base_url=resolve_telegram_api_base_url(bot, global_settings),
                    on_rate_limit=_on_telegram_rate_limit,
                )
                try:
                    await client.register_webhook(
                        public_url=str(bot.webhook.public_url),
                        secret_token=str(bot.webhook.secret_token),
                    )
                    LOGGER.info("gateway webhook registered bot=%s", bot.bot_id)
                except TelegramApiError as error:
                    LOGGER.warning("gateway webhook registration failed bot=%s: %s", bot.bot_id, error)
            else:
                LOGGER.info("gateway bot=%s polling mode (webhook registration skipped)", bot.bot_id)

        try:
            yield
        finally:
            await repository.dispose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/readyz")
    async def readyz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/metrics")
    async def metrics() -> dict:
        return await repository.get_metrics(bot_id=None)

    @app.post("/telegram/webhook/{bot_id}/{path_secret}")
    async def telegram_webhook(
        bot_id: str,
        path_secret: str,
        payload: dict,
        x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
    ) -> dict[str, bool]:
        bot = bot_map.get(bot_id)
        if bot is None:
            await _inc_metric(GLOBAL_METRICS_BOT_ID, "webhook_reject_unknown_bot")
            raise HTTPException(status_code=404, detail="bot not found")
        if bot.webhook.path_secret and path_secret != bot.webhook.path_secret:
            await _inc_metric(str(bot.bot_id), "webhook_reject_invalid_path_secret")
            raise HTTPException(status_code=401, detail="invalid path secret")
        if bot.webhook.secret_token and x_telegram_bot_api_secret_token != bot.webhook.secret_token:
            await _inc_metric(str(bot.bot_id), "webhook_reject_invalid_secret_token")
            raise HTTPException(status_code=401, detail="invalid secret token")

        update_id = payload.get("update_id")
        if not isinstance(update_id, int):
            await _inc_metric(str(bot.bot_id), "webhook_reject_invalid_update")
            raise HTTPException(status_code=400, detail="update_id is required")

        now = _now_ms()
        accepted = await repository.insert_telegram_update(
            bot_id=str(bot.bot_id),
            update_id=update_id,
            chat_id=extract_chat_id(payload),
            payload_json=json.dumps(payload, ensure_ascii=False),
            received_at=now,
        )
        if accepted:
            await repository.enqueue_telegram_update_job(bot_id=str(bot.bot_id), update_id=update_id, available_at=now)
            await _inc_metric(str(bot.bot_id), "webhook_accept_total")
        else:
            await _inc_metric(str(bot.bot_id), "webhook_duplicate_update")

        return {"ok": True}

    config = uvicorn.Config(app, host=host, port=port, log_level=global_settings.log_level.lower())
    server = uvicorn.Server(config)
    await server.serve()
