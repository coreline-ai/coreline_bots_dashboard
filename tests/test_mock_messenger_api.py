from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telegram_bot_new.mock_messenger.api import create_app
from telegram_bot_new.mock_messenger.store import MockMessengerStore


@pytest.fixture
def mock_client(tmp_path: Path):
    store = MockMessengerStore(
        db_path=str(tmp_path / "mock.db"),
        data_dir=str(tmp_path / "data"),
    )
    app = create_app(store=store, allow_get_updates_with_webhook=False)
    with TestClient(app) as client:
        yield client
    store.close()


def test_telegram_api_contract_endpoints(mock_client: TestClient) -> None:
    token = "token-a"

    set_webhook = mock_client.post(
        f"/bot{token}/setWebhook",
        json={"url": "http://localhost:9999/hook", "secret_token": "sec-1"},
    )
    assert set_webhook.status_code == 200
    assert set_webhook.json()["ok"] is True

    send_message = mock_client.post(
        f"/bot{token}/sendMessage",
        json={"chat_id": 101, "text": "hello from bot"},
    )
    assert send_message.status_code == 200
    payload = send_message.json()
    assert payload["ok"] is True
    assert payload["result"]["message_id"] == 1

    edit_message = mock_client.post(
        f"/bot{token}/editMessageText",
        json={"chat_id": 101, "message_id": 1, "text": "edited"},
    )
    assert edit_message.status_code == 200
    assert edit_message.json()["result"]["text"] == "edited"

    answer_callback = mock_client.post(
        f"/bot{token}/answerCallbackQuery",
        json={"callback_query_id": "cb-1", "text": "ok"},
    )
    assert answer_callback.status_code == 200
    assert answer_callback.json()["result"] is True

    send_document = mock_client.post(
        f"/bot{token}/sendDocument",
        data={"chat_id": "101", "caption": "doc"},
        files={"document": ("readme.txt", b"hello", "text/plain")},
    )
    assert send_document.status_code == 200
    doc_payload = send_document.json()
    assert doc_payload["ok"] is True
    assert doc_payload["result"]["document"]["file_name"] == "readme.txt"

    send_photo = mock_client.post(
        f"/bot{token}/sendPhoto",
        data={"chat_id": "101", "caption": "preview"},
        files={"photo": ("preview.png", b"\x89PNG\r\n\x1a\nmock", "image/png")},
    )
    assert send_photo.status_code == 200
    photo_payload = send_photo.json()
    assert photo_payload["ok"] is True
    assert photo_payload["result"]["document"]["file_name"] == "preview.png"

    delete_webhook = mock_client.post(f"/bot{token}/deleteWebhook", json={"drop_pending_updates": False})
    assert delete_webhook.status_code == 200
    assert delete_webhook.json()["ok"] is True


def test_rate_limit_429_emulation(mock_client: TestClient) -> None:
    token = "token-b"

    set_rule = mock_client.post(
        "/_mock/rate_limit",
        json={"token": token, "method": "getUpdates", "count": 1, "retry_after": 2},
    )
    assert set_rule.status_code == 200
    assert set_rule.json()["ok"] is True

    first = mock_client.post(f"/bot{token}/getUpdates", json={})
    assert first.status_code == 429
    body = first.json()
    assert body["ok"] is False
    assert body["error_code"] == 429
    assert body["parameters"]["retry_after"] == 2

    second = mock_client.post(f"/bot{token}/getUpdates", json={})
    assert second.status_code == 200
    assert second.json()["ok"] is True


def test_document_metadata_and_download_endpoint(mock_client: TestClient) -> None:
    token = "token-doc"
    chat_id = 202

    send_document = mock_client.post(
        f"/bot{token}/sendDocument",
        data={"chat_id": str(chat_id), "caption": "render image"},
        files={"document": ("preview.png", b"\x89PNG\r\n\x1a\nmock", "image/png")},
    )
    assert send_document.status_code == 200
    assert send_document.json()["ok"] is True

    timeline = mock_client.get(f"/_mock/messages?token={token}&chat_id={chat_id}&limit=10")
    assert timeline.status_code == 200
    messages = timeline.json()["result"]["messages"]
    assert len(messages) == 1

    document = messages[0]["document"]
    assert document["filename"] == "preview.png"
    assert document["is_image"] is True
    assert isinstance(document["id"], int)
    assert isinstance(document["url"], str)
    assert document["url"].startswith("/_mock/document/")

    download = mock_client.get(document["url"])
    assert download.status_code == 200
    assert download.content.startswith(b"\x89PNG")

    send_html = mock_client.post(
        f"/bot{token}/sendDocument",
        data={"chat_id": str(chat_id), "caption": "landing page"},
        files={"document": ("landing.html", b"<html><body>Landing</body></html>", "text/html")},
    )
    assert send_html.status_code == 200
    assert send_html.json()["ok"] is True

    timeline_html = mock_client.get(f"/_mock/messages?token={token}&chat_id={chat_id}&limit=10")
    html_messages = timeline_html.json()["result"]["messages"]
    html_document = html_messages[-1]["document"]
    assert html_document["filename"] == "landing.html"
    assert html_document["is_image"] is False
    assert html_document["is_html"] is True

    html_download = mock_client.get(html_document["url"])
    assert html_download.status_code == 200
    assert "text/html" in (html_download.headers.get("content-type") or "")
