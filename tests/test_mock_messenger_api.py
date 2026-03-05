from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import yaml

from telegram_bot_new.mock_messenger.api import create_app
from telegram_bot_new.mock_messenger.store import MockMessengerStore
from telegram_bot_new.settings import get_global_settings


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


def test_update_id_monotonic_after_clear(mock_client: TestClient) -> None:
    token = "token-clear-monotonic"
    chat_id = 505

    first = mock_client.post(
        "/_mock/send",
        json={"token": token, "chat_id": chat_id, "user_id": 9001, "text": "first"},
    )
    assert first.status_code == 200
    first_update_id = int(first.json()["result"]["update_id"])

    cleared = mock_client.post(
        "/_mock/messages/clear",
        json={"token": token, "chat_id": chat_id},
    )
    assert cleared.status_code == 200
    assert cleared.json()["ok"] is True

    second = mock_client.post(
        "/_mock/send",
        json={"token": token, "chat_id": chat_id, "user_id": 9001, "text": "second"},
    )
    assert second.status_code == 200
    second_update_id = int(second.json()["result"]["update_id"])

    assert second_update_id > first_update_id


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
        assert bots[0]["default_role"] == "implementer"
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


def test_mock_bot_diagnostics_rejects_bot_token_mismatch(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "diagnostics-mismatch.db"),
        data_dir=str(tmp_path / "diagnostics-mismatch-data"),
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
        response = client.get(
            "/_mock/bot_diagnostics",
            params={"bot_id": "bot-a", "token": "mock_token_b", "chat_id": 1001, "limit": 120},
        )
        assert response.status_code == 400
        assert "token does not match bot_id" in response.json()["detail"]
    store.close()


def test_mock_projects_endpoint_lists_workspace_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "projects.db"),
        data_dir=str(tmp_path / "projects-data"),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    project_a = workspace / "project-a"
    project_a.mkdir(parents=True, exist_ok=True)
    (project_a / "package.json").write_text('{"name":"project-a"}', encoding="utf-8")
    monkeypatch.chdir(workspace)

    app = create_app(store=store, allow_get_updates_with_webhook=False)
    with TestClient(app) as client:
        response = client.get("/_mock/projects")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        projects = payload["result"]["projects"]
        paths = [row["path"] for row in projects]
        assert str(workspace.resolve()) in paths
        assert str(project_a.resolve()) in paths
    store.close()


def test_mock_skills_endpoint_lists_local_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "skills.db"),
        data_dir=str(tmp_path / "skills-data"),
    )
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "demo-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: demo skill desc\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BOT_SKILLS_DIR", str(skills_root))

    app = create_app(store=store, allow_get_updates_with_webhook=False)
    with TestClient(app) as client:
        response = client.get("/_mock/skills")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        skills = payload["result"]["skills"]
        assert len(skills) == 1
        assert skills[0]["skill_id"] == "demo-skill"
        assert skills[0]["name"] == "demo-skill"
    store.close()


def test_mock_control_tower_endpoint_returns_bot_rows(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "control-tower.db"),
        data_dir=str(tmp_path / "control-tower-data"),
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
        response = client.get("/_mock/control_tower")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        rows = payload["result"]["rows"]
        assert isinstance(rows, list)
        assert len(rows) == 3
        first = rows[0]
        assert first["bot_id"] in {"bot-a", "bot-b", "bot-c"}
        assert first["state"] in {"healthy", "degraded", "failing"}
        assert first["recommended_action"] in {"none", "observe", "stop_run", "restart_session"}
    store.close()


def test_mock_runtime_profile_endpoint(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "runtime-profile.db"),
        data_dir=str(tmp_path / "runtime-profile-data"),
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
        response = client.get("/_mock/runtime_profile")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        result = payload["result"]
        assert result["effective_bots"] == 3
        assert result["source_bots"] == 3
        assert isinstance(result["is_capped"], bool)
        assert str(result["bots_config_path"]).endswith("bots.yaml")
    store.close()


def test_bot_diagnostics_unknown_bot_includes_cap_hint_when_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cap-hint.db"),
        data_dir=str(tmp_path / "cap-hint-data"),
    )
    workspace = tmp_path / "workspace"
    config_dir = workspace / "config"
    runtime_dir = workspace / ".runlogs" / "local-multibot"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    source_config = config_dir / "bots.multibot.yaml"
    _write_bots_yaml(source_config)
    source_payload = yaml.safe_load(source_config.read_text(encoding="utf-8")) or {}
    source_bots = list(source_payload.get("bots") or [])
    effective_payload = {"bots": source_bots[:2]}
    effective_config = runtime_dir / "bots.effective.yaml"
    effective_config.write_text(yaml.safe_dump(effective_payload, sort_keys=False), encoding="utf-8")

    monkeypatch.chdir(workspace)
    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(effective_config),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
    )
    with TestClient(app) as client:
        response = client.get(
            "/_mock/bot_diagnostics",
            params={"bot_id": "bot-c", "token": "mock_token_c", "chat_id": 1001, "limit": 120},
        )
        assert response.status_code == 404
        detail = str(response.json().get("detail") or "")
        assert "unknown bot_id: bot-c" in detail
        assert "excluded by MAX_BOTS cap" in detail
        assert "MAX_BOTS>=3" in detail
    store.close()


def test_mock_control_tower_recover_stop_run_enqueues_stop(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "control-recover.db"),
        data_dir=str(tmp_path / "control-recover-data"),
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
        response = client.post(
            "/_mock/control_tower/recover",
            json={"bot_id": "bot-a", "chat_id": 1001, "user_id": 9001, "strategy": "stop_run"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["result"]["bot_id"] == "bot-a"
        assert payload["result"]["strategy"] == "stop_run"
        commands = payload["result"]["commands"]
        assert len(commands) == 1
        assert commands[0]["text"] == "/stop"

        messages = client.get("/_mock/messages", params={"token": "mock_token_a", "chat_id": 1001, "limit": 10}).json()
        user_texts = [row["text"] for row in messages["result"]["messages"] if row["direction"] == "user"]
        assert "/stop" in user_texts
    store.close()


def test_mock_forensics_bundle_endpoint(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "forensics-bundle.db"),
        data_dir=str(tmp_path / "forensics-bundle-data"),
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
        send_response = client.post(
            "/_mock/send",
            json={"token": "mock_token_a", "chat_id": 1001, "user_id": 9001, "text": "forensics hello"},
        )
        assert send_response.status_code == 200

        response = client.get(
            "/_mock/forensics/bundle",
            params={"bot_id": "bot-a", "token": "mock_token_a", "chat_id": 1001, "limit": 50},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        result = payload["result"]
        assert result["bot_id"] == "bot-a"
        assert result["token"] == "mock_token_a"
        assert result["chat_id"] == 1001
        assert "runtime_profile" in result
        assert "state" in result
        assert "slo" in result
        assert isinstance(result["diagnostics"], dict)
        assert isinstance(result["audit_logs"], list)
        assert isinstance(result["messages"], list)
        assert isinstance(result["updates"], list)
    store.close()


def test_mock_routing_suggest_endpoint(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "routing-suggest.db"),
        data_dir=str(tmp_path / "routing-suggest-data"),
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
        response = client.get(
            "/_mock/routing/suggest",
            params={"text": "@auto 코드 리팩토링", "bot_id": "bot-a"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        result = payload["result"]
        assert result["enabled"] is True
        assert result["task_type"] == "code"
        assert result["provider"] == "codex"
        assert isinstance(result["model"], str)
        assert result["stripped_prompt"] == "코드 리팩토링"
    store.close()


def test_mock_audit_logs_endpoint_with_bot_down(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "audit-down.db"),
        data_dir=str(tmp_path / "audit-down-data"),
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
        response = client.get(
            "/_mock/audit_logs",
            params={"bot_id": "bot-a", "chat_id": 1001, "limit": 30},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        result = payload["result"]
        assert isinstance(result["logs"], list)
        assert result["logs"] == []
        assert isinstance(result["embedded_error"], str)
        assert result["embedded_error"]
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
        assert row["bot_id"] == "bot-d"
        assert isinstance(row["token"], str)
        assert row["token"]
        assert row["token"] == "mock_token_d"
        assert row["name"] == "Bot D"

        after = client.get("/_mock/bot_catalog").json()["result"]["bots"]
        assert len(after) == len(before) + 1
        assert any(item["bot_id"] == row["bot_id"] for item in after)
    store.close()


def test_mock_bot_catalog_add_reuses_deleted_alpha_slot(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-add-reuse.db"),
        data_dir=str(tmp_path / "catalog-add-reuse-data"),
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
        deleted = client.post("/_mock/bot_catalog/delete", json={"bot_id": "bot-b"})
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True

        created = client.post("/_mock/bot_catalog/add", json={"adapter": "codex"})
        assert created.status_code == 200
        payload = created.json()
        assert payload["ok"] is True
        row = payload["result"]["bot"]
        assert row["bot_id"] == "bot-b"
        assert row["name"] == "Bot B"
        assert row["token"] == "mock_token_b"
    store.close()


def test_mock_bot_catalog_add_persists_into_source_config_for_effective_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    config_dir = workspace / "config"
    runtime_dir = workspace / ".runlogs" / "simulated"
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    source_config = config_dir / "bots.multibot.yaml"
    _write_bots_yaml(source_config)

    source_payload = yaml.safe_load(source_config.read_text(encoding="utf-8")) or {}
    effective_config = runtime_dir / "bots.effective.yaml"
    effective_config.write_text(yaml.safe_dump(source_payload, sort_keys=False), encoding="utf-8")

    monkeypatch.chdir(workspace)
    store = MockMessengerStore(
        db_path=str(workspace / "catalog-add-sync.db"),
        data_dir=str(workspace / "catalog-add-sync-data"),
    )
    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(effective_config),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
    )
    with TestClient(app) as client:
        created = client.post("/_mock/bot_catalog/add", json={"adapter": "codex"})
        assert created.status_code == 200
        payload = created.json()
        assert payload["ok"] is True
        assert payload["result"]["bot"]["bot_id"] == "bot-d"

    store.close()

    source_after = yaml.safe_load(source_config.read_text(encoding="utf-8")) or {}
    source_ids = [str(item.get("bot_id")) for item in list(source_after.get("bots") or []) if isinstance(item, dict)]
    assert "bot-d" in source_ids

    # Simulate local-multibot restart regeneration: effective config is rebuilt from source config.
    effective_config.write_text(
        yaml.safe_dump({"bots": list(source_after.get("bots") or [])}, sort_keys=False),
        encoding="utf-8",
    )

    store_restarted = MockMessengerStore(
        db_path=str(workspace / "catalog-add-sync-restarted.db"),
        data_dir=str(workspace / "catalog-add-sync-restarted-data"),
    )
    app_restarted = create_app(
        store=store_restarted,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(effective_config),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
    )
    with TestClient(app_restarted) as client:
        catalog = client.get("/_mock/bot_catalog")
        assert catalog.status_code == 200
        ids_after_restart = [row["bot_id"] for row in catalog.json()["result"]["bots"]]
        assert "bot-d" in ids_after_restart
    store_restarted.close()


def test_mock_bot_catalog_delete_endpoint(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-delete.db"),
        data_dir=str(tmp_path / "catalog-delete-data"),
    )
    bots_yaml = tmp_path / "bots.yaml"
    _write_bots_yaml(bots_yaml)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    bot_a_state_db = state_dir / "bot-a.db"
    bot_a_state_db.write_text("placeholder", encoding="utf-8")

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
        assert bot_a_state_db.exists() is False

        after = client.get("/_mock/bot_catalog").json()["result"]["bots"]
        assert all(row["bot_id"] != "bot-a" for row in after)

        missing = client.post("/_mock/bot_catalog/delete", json={"bot_id": "does-not-exist"})
        assert missing.status_code == 404
    store.close()


def test_mock_bot_catalog_delete_endpoint_removes_custom_sqlite_db_path(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-delete-custom.db"),
        data_dir=str(tmp_path / "catalog-delete-custom-data"),
    )
    custom_state_dir = tmp_path / "custom-state"
    custom_state_dir.mkdir(parents=True, exist_ok=True)
    custom_db = custom_state_dir / "bot-x.db"
    custom_db.write_text("placeholder", encoding="utf-8")

    bots_yaml = tmp_path / "bots-custom.yaml"
    payload = {
        "bots": [
            {
                "bot_id": "bot-x",
                "name": "Bot X",
                "mode": "embedded",
                "telegram_token": "mock_token_x",
                "adapter": "codex",
                "database_url": f"sqlite+aiosqlite:///{custom_db.as_posix()}",
                "webhook": {
                    "path_secret": "bot-x-path",
                    "secret_token": "bot-x-secret",
                },
            }
        ]
    }
    bots_yaml.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(bots_yaml),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
    )
    with TestClient(app) as client:
        deleted = client.post("/_mock/bot_catalog/delete", json={"bot_id": "bot-x"})
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True

    assert custom_db.exists() is False
    store.close()


def test_mock_bot_catalog_role_update_for_three_bots(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-role.db"),
        data_dir=str(tmp_path / "catalog-role-data"),
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
        role_updates = {
            "bot-a": "controller",
            "bot-b": "planner",
            "bot-c": "qa",
        }
        for bot_id, role in role_updates.items():
            response = client.post("/_mock/bot_catalog/role", json={"bot_id": bot_id, "role": role})
            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] is True
            assert payload["result"]["bot"]["bot_id"] == bot_id
            assert payload["result"]["bot"]["default_role"] == role
    store.close()


def test_mock_bot_catalog_name_update_endpoint(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-name.db"),
        data_dir=str(tmp_path / "catalog-name-data"),
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
        response = client.post("/_mock/bot_catalog/name", json={"bot_id": "bot-a", "name": "Alpha Bot"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["result"]["bot"]["bot_id"] == "bot-a"
        assert payload["result"]["bot"]["name"] == "Alpha Bot"

        catalog = client.get("/_mock/bot_catalog")
        assert catalog.status_code == 200
        bots = catalog.json()["result"]["bots"]
        selected = next((row for row in bots if row["bot_id"] == "bot-a"), None)
        assert selected is not None
        assert selected["name"] == "Alpha Bot"
    store.close()


def test_mock_bot_catalog_name_update_endpoint_rejects_blank_name(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-name-blank.db"),
        data_dir=str(tmp_path / "catalog-name-blank-data"),
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
        response = client.post("/_mock/bot_catalog/name", json={"bot_id": "bot-a", "name": "   "})
        assert response.status_code == 400
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
        assert payload["result"]["bot"]["default_adapter"] == "codex"
    assert missing_config.exists()
    store.close()


def test_mock_routing_suggest_defaults_to_codex_without_bot_id(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "routing-default.db"),
        data_dir=str(tmp_path / "routing-default-data"),
    )
    app = create_app(
        store=store,
        allow_get_updates_with_webhook=False,
        bots_config_path=str(tmp_path / "missing.yaml"),
    )
    with TestClient(app) as client:
        response = client.get("/_mock/routing/suggest", params={"text": "@auto 테스트"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["result"]["provider"] == "codex"
    store.close()


def test_mock_bot_catalog_add_endpoint_rolls_back_when_config_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "catalog-add-strict.db"),
        data_dir=str(tmp_path / "catalog-add-strict-data"),
    )
    bots_yaml = tmp_path / "bots.yaml"
    _write_bots_yaml(bots_yaml)
    monkeypatch.setenv("STRICT_BOT_DB_ISOLATION", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:////tmp/mock-global.db")
    get_global_settings.cache_clear()

    try:
        app = create_app(
            store=store,
            allow_get_updates_with_webhook=False,
            bots_config_path=str(bots_yaml),
            embedded_host="127.0.0.1",
            embedded_base_port=8600,
        )
        with TestClient(app) as client:
            created = client.post("/_mock/bot_catalog/add", json={"adapter": "gemini"})
            assert created.status_code == 400
            assert "failed to add bot" in created.json()["detail"]
    finally:
        get_global_settings.cache_clear()
        store.close()
