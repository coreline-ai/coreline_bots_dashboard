from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import telegram_bot_new.mock_messenger.api as mock_api
from telegram_bot_new.mock_messenger.api import create_app
from telegram_bot_new.mock_messenger.store import MockMessengerStore


def test_webhook_delivery_includes_secret_and_marks_delivered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_post_webhook_update(*, url: str, secret_token: str | None, payload: dict):
        calls.append({"url": url, "secret_token": secret_token, "payload": payload})
        return True, None

    monkeypatch.setattr(mock_api, "_post_webhook_update", fake_post_webhook_update)

    store = MockMessengerStore(
        db_path=str(tmp_path / "webhook.db"),
        data_dir=str(tmp_path / "webhook-data"),
    )
    app = create_app(store=store, allow_get_updates_with_webhook=False)

    with TestClient(app) as client:
        token = "token-hook"
        set_webhook = client.post(
            f"/bot{token}/setWebhook",
            json={"url": "http://127.0.0.1:9999/hook", "secret_token": "hook-secret"},
        )
        assert set_webhook.status_code == 200

        send = client.post(
            "/_mock/send",
            json={"token": token, "chat_id": 1002, "user_id": 9003, "text": "webhook ping"},
        )
        assert send.status_code == 200
        result = send.json()["result"]
        assert result["delivery_mode"] == "webhook"
        assert result["delivered_via_webhook"] is True

        assert len(calls) == 1
        assert calls[0]["url"] == "http://127.0.0.1:9999/hook"
        assert calls[0]["secret_token"] == "hook-secret"
        assert calls[0]["payload"]["message"]["text"] == "webhook ping"

        # webhook active + debug off => getUpdates must stay empty
        updates = client.post(f"/bot{token}/getUpdates", json={})
        assert updates.status_code == 200
        assert updates.json()["result"] == []

    store.close()


def test_webhook_failure_can_be_observed_with_debug_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post_webhook_update(*, url: str, secret_token: str | None, payload: dict):
        return False, "forced webhook failure"

    monkeypatch.setattr(mock_api, "_post_webhook_update", fake_post_webhook_update)

    store = MockMessengerStore(
        db_path=str(tmp_path / "webhook-debug.db"),
        data_dir=str(tmp_path / "webhook-debug-data"),
    )
    app = create_app(store=store, allow_get_updates_with_webhook=True)

    with TestClient(app) as client:
        token = "token-debug"
        client.post(
            f"/bot{token}/setWebhook",
            json={"url": "http://127.0.0.1:9999/hook", "secret_token": "sec"},
        )
        send = client.post(
            "/_mock/send",
            json={"token": token, "chat_id": 1003, "user_id": 9004, "text": "debug path"},
        )
        assert send.status_code == 200
        assert send.json()["result"]["delivered_via_webhook"] is False

        updates = client.post(f"/bot{token}/getUpdates", json={})
        assert updates.status_code == 200
        result = updates.json()["result"]
        assert len(result) == 1
        assert result[0]["message"]["text"] == "debug path"

    store.close()
