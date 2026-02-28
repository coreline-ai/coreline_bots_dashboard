from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, Header, HTTPException

from telegram_bot_new.db.repository import Repository, create_repository
from telegram_bot_new.services.run_service import RunService
from telegram_bot_new.services.action_token_service import ActionTokenService
from telegram_bot_new.services.button_prompt_service import ButtonPromptService
from telegram_bot_new.services.session_service import SessionService
from telegram_bot_new.services.summary_service import SummaryService
from telegram_bot_new.services.youtube_search_service import YoutubeSearchService
from telegram_bot_new.settings import (
    BotConfig,
    GlobalSettings,
    resolve_bot_database_url,
    resolve_telegram_api_base_url,
)
from telegram_bot_new.streaming.telegram_event_streamer import TelegramEventStreamer
from telegram_bot_new.telegram.api import extract_chat_id
from telegram_bot_new.telegram.client import TelegramApiError, TelegramClient
from telegram_bot_new.telegram.commands import BotIdentity, TelegramCommandHandler
from telegram_bot_new.telegram.poller import run_telegram_poller
from telegram_bot_new.workers.run_worker import run_cli_worker
from telegram_bot_new.workers.update_worker import run_update_worker

LOGGER = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _is_local_mock_base_url(base_url: str) -> bool:
    normalized = (base_url or "").strip().lower()
    return normalized.startswith("http://127.0.0.1") or normalized.startswith("http://localhost")


async def run_embedded_bot(bot: BotConfig, global_settings: GlobalSettings, host: str, port: int) -> None:
    logging.basicConfig(level=getattr(logging, global_settings.log_level.upper(), logging.INFO))

    repository = create_repository(resolve_bot_database_url(bot, global_settings))

    async def _inc_metric(metric_key: str) -> None:
        try:
            await repository.increment_runtime_metric(
                bot_id=str(bot.bot_id),
                metric_key=metric_key,
                now=_now_ms(),
            )
        except Exception:
            LOGGER.exception("failed to increment runtime metric bot=%s metric=%s", bot.bot_id, metric_key)

    async def _on_telegram_rate_limit(method: str, retry_after: int) -> None:
        await _inc_metric("telegram_rate_limit_retry_total")
        await _inc_metric(f"telegram_rate_limit_retry.{method}")

    telegram_base_url = resolve_telegram_api_base_url(bot, global_settings)
    telegram_client = TelegramClient(
        bot.telegram_token,
        base_url=telegram_base_url,
        on_rate_limit=_on_telegram_rate_limit,
    )

    session_service = SessionService(repository)
    run_service = RunService(repository)
    summary_service = SummaryService()
    youtube_search = YoutubeSearchService()
    action_token_service = ActionTokenService(repository)
    button_prompt_service = ButtonPromptService()
    streamer = TelegramEventStreamer(telegram_client)
    command_handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id=str(bot.bot_id),
            bot_name=str(bot.name),
            adapter=bot.adapter,
            owner_user_id=bot.owner_user_id,
            default_models={
                "codex": bot.codex.model,
                "gemini": bot.gemini.model,
                "claude": bot.claude.model,
            },
        ),
        client=telegram_client,
        session_service=session_service,
        run_service=run_service,
        repository=repository,
        youtube_search=youtube_search,
        action_token_service=action_token_service,
        button_prompt_service=button_prompt_service,
    )

    stop_event = asyncio.Event()
    worker_tasks: list[asyncio.Task[None]] = []

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await repository.create_schema()
        await repository.upsert_bot(
            bot_id=str(bot.bot_id),
            name=str(bot.name),
            mode=bot.mode,
            owner_user_id=bot.owner_user_id or 0,
            adapter_name=bot.adapter,
            now=_now_ms(),
        )
        if bot.ingest_mode == "webhook":
            try:
                await telegram_client.register_webhook(
                    public_url=str(bot.webhook.public_url),
                    secret_token=str(bot.webhook.secret_token),
                )
                LOGGER.info("embedded bot=%s webhook registered", bot.bot_id)
            except TelegramApiError as error:
                LOGGER.warning("embedded bot=%s webhook registration failed: %s", bot.bot_id, error)
        else:
            LOGGER.info("embedded bot=%s polling mode enabled", bot.bot_id)
            worker_tasks.append(
                asyncio.create_task(
                    run_telegram_poller(
                        bot_id=str(bot.bot_id),
                        repository=repository,
                        client=telegram_client,
                        poll_interval_ms=global_settings.worker_poll_interval_ms,
                        stop_event=stop_event,
                        ignore_persisted_offset=_is_local_mock_base_url(telegram_base_url),
                    )
                )
            )

        worker_tasks.append(
            asyncio.create_task(
                run_update_worker(
                    bot_id=str(bot.bot_id),
                    repository=repository,
                    handler=command_handler,
                    lease_ms=global_settings.job_lease_ms,
                    poll_interval_ms=global_settings.worker_poll_interval_ms,
                    stop_event=stop_event,
                )
            )
        )
        worker_tasks.append(
            asyncio.create_task(
                run_cli_worker(
                    bot_id=str(bot.bot_id),
                    repository=repository,
                    telegram_client=telegram_client,
                    streamer=streamer,
                    summary_service=summary_service,
                    default_models_by_provider={
                        "codex": bot.codex.model,
                        "gemini": bot.gemini.model,
                        "claude": bot.claude.model,
                    },
                    default_sandbox=bot.codex.sandbox,
                    lease_ms=global_settings.job_lease_ms,
                    poll_interval_ms=global_settings.worker_poll_interval_ms,
                    stop_event=stop_event,
                )
            )
        )

        try:
            yield
        finally:
            stop_event.set()
            for task in worker_tasks:
                task.cancel()
            for task in worker_tasks:
                with suppress(asyncio.CancelledError):
                    await task
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
        return await repository.get_metrics(bot_id=str(bot.bot_id))

    @app.post("/telegram/webhook/{bot_id}/{path_secret}")
    async def telegram_webhook(
        bot_id: str,
        path_secret: str,
        payload: dict,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if bot_id != str(bot.bot_id):
            await _inc_metric("webhook_reject_unknown_bot")
            raise HTTPException(status_code=404, detail="bot not found")
        if bot.webhook.path_secret and path_secret != bot.webhook.path_secret:
            await _inc_metric("webhook_reject_invalid_path_secret")
            raise HTTPException(status_code=401, detail="invalid path secret")
        if bot.webhook.secret_token and x_telegram_bot_api_secret_token != bot.webhook.secret_token:
            await _inc_metric("webhook_reject_invalid_secret_token")
            raise HTTPException(status_code=401, detail="invalid secret token")

        update_id = payload.get("update_id")
        if not isinstance(update_id, int):
            await _inc_metric("webhook_reject_invalid_update")
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
            await _inc_metric("webhook_accept_total")
        else:
            await _inc_metric("webhook_duplicate_update")

        return {"ok": True}

    config = uvicorn.Config(app, host=host, port=port, log_level=global_settings.log_level.lower())
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot_workers_only(bot: BotConfig, global_settings: GlobalSettings) -> None:
    logging.basicConfig(level=getattr(logging, global_settings.log_level.upper(), logging.INFO))

    repository = create_repository(resolve_bot_database_url(bot, global_settings))

    async def _inc_metric(metric_key: str) -> None:
        try:
            await repository.increment_runtime_metric(
                bot_id=str(bot.bot_id),
                metric_key=metric_key,
                now=_now_ms(),
            )
        except Exception:
            LOGGER.exception("failed to increment runtime metric bot=%s metric=%s", bot.bot_id, metric_key)

    async def _on_telegram_rate_limit(method: str, retry_after: int) -> None:
        await _inc_metric("telegram_rate_limit_retry_total")
        await _inc_metric(f"telegram_rate_limit_retry.{method}")

    telegram_base_url = resolve_telegram_api_base_url(bot, global_settings)
    telegram_client = TelegramClient(
        bot.telegram_token,
        base_url=telegram_base_url,
        on_rate_limit=_on_telegram_rate_limit,
    )
    session_service = SessionService(repository)
    run_service = RunService(repository)
    summary_service = SummaryService()
    youtube_search = YoutubeSearchService()
    action_token_service = ActionTokenService(repository)
    button_prompt_service = ButtonPromptService()
    streamer = TelegramEventStreamer(telegram_client)
    command_handler = TelegramCommandHandler(
        bot=BotIdentity(
            bot_id=str(bot.bot_id),
            bot_name=str(bot.name),
            adapter=bot.adapter,
            owner_user_id=bot.owner_user_id,
            default_models={
                "codex": bot.codex.model,
                "gemini": bot.gemini.model,
                "claude": bot.claude.model,
            },
        ),
        client=telegram_client,
        session_service=session_service,
        run_service=run_service,
        repository=repository,
        youtube_search=youtube_search,
        action_token_service=action_token_service,
        button_prompt_service=button_prompt_service,
    )

    await repository.create_schema()
    await repository.upsert_bot(
        bot_id=str(bot.bot_id),
        name=str(bot.name),
        mode=bot.mode,
        owner_user_id=bot.owner_user_id or 0,
        adapter_name=bot.adapter,
        now=_now_ms(),
    )

    stop_event = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []

    if bot.ingest_mode == "polling":
        LOGGER.info("worker bot=%s polling mode enabled", bot.bot_id)
        tasks.append(
            asyncio.create_task(
                run_telegram_poller(
                    bot_id=str(bot.bot_id),
                    repository=repository,
                    client=telegram_client,
                    poll_interval_ms=global_settings.worker_poll_interval_ms,
                    stop_event=stop_event,
                    ignore_persisted_offset=_is_local_mock_base_url(telegram_base_url),
                )
            )
        )

    tasks.extend(
        [
            asyncio.create_task(
                run_update_worker(
                    bot_id=str(bot.bot_id),
                    repository=repository,
                    handler=command_handler,
                    lease_ms=global_settings.job_lease_ms,
                    poll_interval_ms=global_settings.worker_poll_interval_ms,
                    stop_event=stop_event,
                )
            ),
            asyncio.create_task(
                run_cli_worker(
                    bot_id=str(bot.bot_id),
                    repository=repository,
                    telegram_client=telegram_client,
                    streamer=streamer,
                    summary_service=summary_service,
                    default_models_by_provider={
                        "codex": bot.codex.model,
                        "gemini": bot.gemini.model,
                        "claude": bot.claude.model,
                    },
                    default_sandbox=bot.codex.sandbox,
                    lease_ms=global_settings.job_lease_ms,
                    poll_interval_ms=global_settings.worker_poll_interval_ms,
                    stop_event=stop_event,
                )
            ),
        ]
    )

    try:
        await asyncio.gather(*tasks)
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await repository.dispose()
