from __future__ import annotations

import asyncio
import json
import logging
import time

from telegram_bot_new.db.repository import Repository
from telegram_bot_new.telegram.api import extract_chat_id
from telegram_bot_new.telegram.client import TelegramApiError, TelegramClient

LOGGER = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


async def run_telegram_poller(
    *,
    bot_id: str,
    repository: Repository,
    client: TelegramClient,
    poll_interval_ms: int,
    stop_event: asyncio.Event,
    ignore_persisted_offset: bool = False,
) -> None:
    try:
        await client.delete_webhook(drop_pending_updates=False)
    except TelegramApiError as error:
        LOGGER.warning("poller deleteWebhook failed bot=%s: %s", bot_id, error)

    # Offset persistence is not currently wired in this codepath. We always start
    # from fresh polling offset and keep it in-memory for this process lifetime.
    offset: int | None = None
    if ignore_persisted_offset:
        LOGGER.info("poller bot=%s using offset=%s (ignore persisted offset)", bot_id, offset)
    else:
        LOGGER.info("poller bot=%s using offset=%s", bot_id, offset)

    sleep_sec = max(0.05, poll_interval_ms / 1000)
    while not stop_event.is_set():
        try:
            updates = await client.get_updates(offset=offset, timeout_sec=25, limit=100)
            if not updates:
                await asyncio.sleep(sleep_sec)
                continue

            for update in updates:
                if stop_event.is_set():
                    return
                update_id = update.get("update_id")
                if not isinstance(update_id, int):
                    continue

                now = _now_ms()
                accepted = await repository.insert_telegram_update(
                    bot_id=bot_id,
                    update_id=update_id,
                    chat_id=extract_chat_id(update),
                    payload_json=json.dumps(update, ensure_ascii=False),
                    received_at=now,
                )
                if accepted:
                    await repository.enqueue_telegram_update_job(
                        bot_id=bot_id,
                        update_id=update_id,
                        available_at=now,
                    )

                if offset is None or update_id >= offset:
                    offset = update_id + 1
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if stop_event.is_set():
                LOGGER.info("telegram poller stopping bot=%s", bot_id)
                return
            LOGGER.warning("telegram poller loop error bot=%s: %s", bot_id, error)
            await asyncio.sleep(1)
