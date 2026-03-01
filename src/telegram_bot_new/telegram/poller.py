from __future__ import annotations

import asyncio
import json
import logging
import time
from queue import Queue
from typing import Any

from telegram_bot_new.db.repository import Repository
from telegram_bot_new.settings import BotConfig
from telegram_bot_new.telegram.api import extract_chat_id
from telegram_bot_new.telegram.client import TelegramApiError, TelegramClient

LOGGER = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class TelegramPoller:
    def __init__(
        self,
        bot_configs: list[BotConfig],
        command_queue: Queue[str] | None = None,
    ):
        self._bot_configs = {b.name: b for b in bot_configs}
        self._command_queue = command_queue
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []
        self._telegram_clients: dict[str, TelegramClient] = {}

    def start(self):
        for bot_config in self._bot_configs.values():
            client = TelegramClient(bot_config.telegram_token)
            self._telegram_clients[bot_config.name] = client
            task = asyncio.create_task(
                self._run_telegram_poller(
                    bot_config=bot_config,
                    client=client,
                )
            )
            self._tasks.append(task)

    def stop(self):
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()

    async def _run_telegram_poller(
        self,
        *,
        bot_config: BotConfig,
        client: TelegramClient,
    ) -> None:
        bot_id = bot_config.name
        # TODO: This should be done in a separate process
        repository = Repository()

        try:
            await client.delete_webhook(drop_pending_updates=False)
        except TelegramApiError as error:
            LOGGER.warning("poller deleteWebhook failed bot=%s: %s", bot_id, error)

        offset = None
        while not self._stop_event.is_set():
            try:
                updates = await client.get_updates(offset=offset, timeout_sec=25, limit=100)
                if not updates:
                    continue

                for update in updates:
                    if self._stop_event.is_set():
                        return

                    if self._try_process_as_command(bot_config, update):
                        update_id = update.get("update_id")
                        if isinstance(update_id, int):
                            if offset is None or update_id >= offset:
                                offset = update_id + 1
                        continue

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
                if self._stop_event.is_set():
                    LOGGER.info("telegram poller stopping bot=%s", bot_id)
                    return
                LOGGER.warning("telegram poller loop error bot=%s: %s", bot_id, error)
                await asyncio.sleep(1)

    def _try_process_as_command(self, bot_config: BotConfig, update: dict[str, Any]) -> bool:
        message = update.get("message")
        if not message or not message.get("text"):
            return False

        text = message["text"]
        if not text.startswith("/"):
            return False

        if not self._is_admin(bot_config, message.get("from", {}).get("id")):
            return False

        command, *args = text[1:].split(" ")
        command = command.lower()

        client = self._telegram_clients[bot_config.name]
        chat_id = message["chat"]["id"]

        if command == "ping":
            asyncio.create_task(self._command_ping(client, chat_id, args))
            return True

        if command == "bot":
            self._command_bot(args)
            return True

        return False

    async def _command_ping(self, client: TelegramClient, chat_id: int, args: list[str]) -> None:
        if not args:
            await client.send_message(chat_id, "pong")
            return

        bot_name = args[0]
        target_client = self._telegram_clients.get(bot_name)

        if not target_client:
            await client.send_message(chat_id, f"Bot '{bot_name}' not found.")
            return

        try:
            result = await target_client.get_me()
            bot_info = result
            response = (
                f"Bot '{bot_name}' is alive.\n"
                f"ID: {bot_info.get('id')}\n"
                f"Name: {bot_info.get('first_name')}\n"
                f"Username: @{bot_info.get('username')}"
            )
        except Exception as e:
            response = f"Bot '{bot_name}' ping failed: {e}"

        await client.send_message(chat_id, response)

    def _command_bot(self, args: list[str]) -> None:
        if not self._command_queue:
            return

        self._command_queue.put(" ".join(args))

    def _is_admin(self, bot_config: BotConfig, user_id: Any) -> bool:
        if not user_id or not isinstance(user_id, int):
            return False
        return not bot_config.admin_ids or user_id in bot_config.admin_ids


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
