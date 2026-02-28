from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telegram_bot_new.mock_messenger.api import create_app
from telegram_bot_new.mock_messenger.store import MockMessengerStore


@pytest.fixture
def polling_client(tmp_path: Path):
    store = MockMessengerStore(
        db_path=str(tmp_path / "polling.db"),
        data_dir=str(tmp_path / "polling-data"),
    )
    app = create_app(store=store, allow_get_updates_with_webhook=False)
    with TestClient(app) as client:
        yield client
    store.close()


def test_polling_flow_end_to_end_and_multi_token_isolation(polling_client: TestClient) -> None:
    token_a = "token-a"
    token_b = "token-b"

    send_user = polling_client.post(
        "/_mock/send",
        json={"token": token_a, "chat_id": 1001, "user_id": 9001, "text": "hi codex"},
    )
    assert send_user.status_code == 200
    assert send_user.json()["ok"] is True

    updates_a = polling_client.post(f"/bot{token_a}/getUpdates", json={})
    assert updates_a.status_code == 200
    result_a = updates_a.json()["result"]
    assert len(result_a) == 1
    assert result_a[0]["message"]["text"] == "hi codex"
    update_id = int(result_a[0]["update_id"])

    no_more = polling_client.post(f"/bot{token_a}/getUpdates", json={"offset": update_id + 1})
    assert no_more.status_code == 200
    assert no_more.json()["result"] == []

    send_bot = polling_client.post(
        f"/bot{token_a}/sendMessage",
        json={"chat_id": 1001, "text": "hello from bot"},
    )
    assert send_bot.status_code == 200
    assert send_bot.json()["result"]["text"] == "hello from bot"

    timeline = polling_client.get(f"/_mock/messages?token={token_a}&chat_id=1001&limit=50")
    assert timeline.status_code == 200
    messages = timeline.json()["result"]["messages"]
    assert [m["direction"] for m in messages] == ["user", "bot"]
    assert messages[0]["text"] == "hi codex"
    assert messages[1]["text"] == "hello from bot"

    # same chat_id, different token must stay isolated
    send_other = polling_client.post(
        "/_mock/send",
        json={"token": token_b, "chat_id": 1001, "user_id": 9002, "text": "other token"},
    )
    assert send_other.status_code == 200

    updates_b = polling_client.post(f"/bot{token_b}/getUpdates", json={})
    assert updates_b.status_code == 200
    result_b = updates_b.json()["result"]
    assert len(result_b) == 1
    assert result_b[0]["message"]["text"] == "other token"

    # token-a should not see token-b updates
    updates_a_after = polling_client.post(f"/bot{token_a}/getUpdates", json={})
    assert updates_a_after.status_code == 200
    assert updates_a_after.json()["result"] == []
