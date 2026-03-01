from __future__ import annotations

import asyncio
from queue import Queue
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_bot_new.settings import BotConfig
from telegram_bot_new.telegram.poller import TelegramPoller


@pytest.fixture
def mock_bot_configs():
    return [
        BotConfig(
            name="bot-1",
            telegram_token="token-1",
            admin_ids=[123],
            codex_model="model-1",
            codex_api_key="key-1",
        ),
        BotConfig(
            name="bot-2",
            telegram_token="token-2",
            admin_ids=[123],
            codex_model="model-2",
            codex_api_key="key-2",
        ),
    ]


@pytest.mark.asyncio
async def test_ping_command_no_args(mock_bot_configs):
    with patch("telegram_bot_new.telegram.poller.TelegramClient") as MockTelegramClient:
        mock_client_instance = MockTelegramClient.return_value
        mock_client_instance.send_message = AsyncMock()

        poller = TelegramPoller(bot_configs=mock_bot_configs)
        poller._telegram_clients = {"bot-1": mock_client_instance}

        await poller._command_ping(mock_client_instance, 12345, [])
        mock_client_instance.send_message.assert_called_once_with(12345, "pong")


@pytest.mark.asyncio
async def test_ping_command_unknown_bot(mock_bot_configs):
    with patch("telegram_bot_new.telegram.poller.TelegramClient") as MockTelegramClient:
        mock_client_instance = MockTelegramClient.return_value
        mock_client_instance.send_message = AsyncMock()

        poller = TelegramPoller(bot_configs=mock_bot_configs)
        poller._telegram_clients = {"bot-1": mock_client_instance}

        await poller._command_ping(mock_client_instance, 12345, ["unknown-bot"])
        mock_client_instance.send_message.assert_called_once_with(12345, "Bot 'unknown-bot' not found.")


@pytest.mark.asyncio
async def test_ping_command_success(mock_bot_configs):
    with patch("telegram_bot_new.telegram.poller.TelegramClient") as MockTelegramClient:
        mock_client_bot1 = MagicMock()
        mock_client_bot1.send_message = AsyncMock()

        mock_client_bot2 = MagicMock()
        mock_client_bot2.get_me = AsyncMock(
            return_value={
                "id": 5678,
                "first_name": "Test Bot",
                "username": "test_bot",
            }
        )

        poller = TelegramPoller(bot_configs=mock_bot_configs)
        poller._telegram_clients = {"bot-1": mock_client_bot1, "bot-2": mock_client_bot2}

        await poller._command_ping(mock_client_bot1, 12345, ["bot-2"])

        expected_response = (
            "Bot 'bot-2' is alive.\n"
            "ID: 5678\n"
            "Name: Test Bot\n"
            "Username: @test_bot"
        )
        mock_client_bot1.send_message.assert_called_once_with(12345, expected_response)


def test_bot_command():
    command_queue = Queue()
    poller = TelegramPoller(bot_configs=[], command_queue=command_queue)

    poller._command_bot(["restart", "bot-1"])
    assert command_queue.get() == "restart bot-1"
