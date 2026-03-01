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


def test_clear_timeline_messages_endpoint(mock_client: TestClient) -> None:
    token = "token-clear"
    chat_id = 303

    first = mock_client.post(
        "/_mock/send",
        json={"token": token, "chat_id": chat_id, "user_id": 9001, "text": "hello"},
    )
    assert first.status_code == 200

    second = mock_client.post(
        f"/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": "bot reply"},
    )
    assert second.status_code == 200
    assert second.json()["ok"] is True

    before = mock_client.get(f"/_mock/messages?token={token}&chat_id={chat_id}&limit=50")
    assert before.status_code == 200
    assert len(before.json()["result"]["messages"]) == 2

    cleared = mock_client.post(
        "/_mock/messages/clear",
        json={"token": token, "chat_id": chat_id},
    )
    assert cleared.status_code == 200
    payload = cleared.json()
    assert payload["ok"] is True
    assert payload["result"]["deleted_messages"] == 2
    assert payload["result"]["deleted_documents"] == 0
    assert payload["result"]["deleted_updates"] >= 1

    after = mock_client.get(f"/_mock/messages?token={token}&chat_id={chat_id}&limit=50")
    assert after.status_code == 200
    assert after.json()["result"]["messages"] == []


def _write_bots_yaml(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "bots:",
                "  - bot_id: bot-a",
                "    name: Bot A",
                "    mode: embedded",
                "    telegram_token: mock_token_a",
                "    adapter: codex",
                "    webhook:",
                "      path_secret: bot-a-path",
                "      secret_token: bot-a-secret",
                "  - bot_id: bot-b",
                "    name: Bot B",
                "    mode: embedded",
                "    telegram_token: mock_token_b",
                "    adapter: gemini",
                "    webhook:",
                "      path_secret: bot-b-path",
                "      secret_token: bot-b-secret",
                "  - bot_id: bot-c",
                "    name: Bot C",
                "    mode: gateway",
                "    telegram_token: mock_token_c",
                "    adapter: claude",
            ]
        ),
        encoding="utf-8",
    )


def test_mock_bot_catalog_endpoint(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog.db"),
        data_dir=str(tmp_path / "catalog-data"),
    )
    bots_yaml = tmp_path / "bots.yaml"
    _write_bots_yaml(bots_yaml)
    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(bots_yaml),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
    )
    with TestClient(app) as client:
        response = client.get("/_mock/bot_catalog")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        bots = payload["result"]["bots"]
        assert len(bots) == 3
        assert bots[0]["bot_id"] == "bot-a"
        assert bots[0]["embedded_url"] == "http://127.0.0.1:8600"
        assert bots[0]["available_models"]["gemini"] == ["gemini-2.5-pro", "gemini-2.5-flash"]
        assert bots[0]["available_models"]["codex"] == [
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
            "gpt-5.2-codex",
            "gpt-5.1-codex-max",
            "gpt-5.2",
            "gpt-5.1-codex-mini",
            "gpt-5",
        ]
        assert bots[0]["available_models"]["claude"] == ["claude-sonnet-4-5"]
        assert bots[1]["bot_id"] == "bot-b"
        assert bots[1]["embedded_url"] == "http://127.0.0.1:8601"
        assert bots[2]["mode"] == "gateway"
        assert bots[2]["embedded_url"] is None
    store.close()


def test_mock_bot_catalog_endpoint_returns_empty_on_missing_config(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-missing.db"),
        data_dir=str(tmp_path / "catalog-missing-data"),
    )
    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(tmp_path / "does-not-exist.yaml"),
    )
    with TestClient(app) as client:
        response = client.get("/_mock/bot_catalog")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["result"]["bots"] == []
    store.close()


def test_mock_bot_diagnostics_endpoint_with_bot_down(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "diagnostics.db"),
        data_dir=str(tmp_path / "diagnostics-data"),
    )
    bots_yaml = tmp_path / "bots.yaml"
    _write_bots_yaml(bots_yaml)
    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(bots_yaml),
        embedded_host="127.0.0.1",
        embedded_base_port=65430,
    )
    with TestClient(app) as client:
        send = client.post(
            "/_mock/send",
            json={"token": "mock_token_a", "chat_id": 1001, "user_id": 9001, "text": "/status"},
        )
        assert send.status_code == 200

        response = client.get(
            "/_mock/bot_diagnostics",
            params={"bot_id": "bot-a", "token": "mock_token_a", "chat_id": 1001, "limit": 120},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        result = payload["result"]
        assert result["health"]["bot"]["ok"] is False
        assert result["metrics"]["in_flight_runs"] is None
        assert result["metrics"]["worker_heartbeat"]["run_worker"] is None
        assert result["metrics"]["worker_heartbeat"]["update_worker"] is None
        assert isinstance(result["threads_top10"], list)
        assert result["last_error_tag"] in {
            "binary_missing",
            "timeout",
            "active_run",
            "parse_error",
            "delivery_error",
            "unknown",
        }
    store.close()


def test_mock_bot_catalog_add_endpoint(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-add.db"),
        data_dir=str(tmp_path / "catalog-add-data"),
    )
    bots_yaml = tmp_path / "bots.yaml"
    _write_bots_yaml(bots_yaml)

    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(bots_yaml),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
    )
    with TestClient(app) as client:
        before = client.get("/_mock/bot_catalog").json()["result"]["bots"]
        before_ids = {row["bot_id"] for row in before}

        created = client.post("/_mock/bot_catalog/add", json={"adapter": "gemini"})
        assert created.status_code == 200
        payload = created.json()
        assert payload["ok"] is True
        row = payload["result"]["bot"]
        assert row["mode"] == "embedded"
        assert row["default_adapter"] == "gemini"
        assert row["bot_id"] not in before_ids
        assert isinstance(row["token"], str)
        assert row["token"]

        after = client.get("/_mock/bot_catalog").json()["result"]["bots"]
        assert len(after) == len(before) + 1
        assert any(item["bot_id"] == row["bot_id"] for item in after)
    store.close()


def test_mock_bot_catalog_delete_endpoint(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-delete.db"),
        data_dir=str(tmp_path / "catalog-delete-data"),
    )
    bots_yaml = tmp_path / "bots.yaml"
    _write_bots_yaml(bots_yaml)

    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(bots_yaml),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
    )
    with TestClient(app) as client:
        deleted = client.post("/_mock/bot_catalog/delete", json={"bot_id": "bot-a"})
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True

        after = client.get("/_mock/bot_catalog").json()["result"]["bots"]
        assert all(row["bot_id"] != "bot-a" for row in after)

        missing = client.post("/_mock/bot_catalog/delete", json={"bot_id": "does-not-exist"})
        assert missing.status_code == 404
    store.close()


def test_mock_bot_catalog_add_endpoint_creates_missing_config(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-create.db"),
        data_dir=str(tmp_path / "catalog-create-data"),
    )
    missing_config = tmp_path / "new-bots.yaml"
    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(missing_config),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
    )
    with TestClient(app) as client:
        created = client.post("/_mock/bot_catalog/add", json={})
        assert created.status_code == 200
        payload = created.json()
        assert payload["ok"] is True
        assert payload["result"]["total_bots"] == 1
    assert missing_config.exists()
    store.close()
