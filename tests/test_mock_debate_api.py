from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient

from telegram_bot_new.mock_messenger.api import create_app
from telegram_bot_new.mock_messenger.store import MockMessengerStore


def _write_bots_yaml(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "bots:",
                "  - bot_id: bot-a",
                "    name: Bot A",
                "    mode: embedded",
                "    telegram_token: mock_token_a",
                "    adapter: gemini",
                "    webhook:",
                "      path_secret: bot-a-path",
                "      secret_token: bot-a-secret",
                "  - bot_id: bot-b",
                "    name: Bot B",
                "    mode: embedded",
                "    telegram_token: mock_token_b",
                "    adapter: codex",
                "    webhook:",
                "      path_secret: bot-b-path",
                "      secret_token: bot-b-secret",
            ]
        ),
        encoding="utf-8",
    )


def _profiles_payload(chat_id: int = 1001, user_id: int = 9001) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": "p-a",
            "label": "Bot A",
            "bot_id": "bot-a",
            "token": "mock_token_a",
            "chat_id": chat_id,
            "user_id": user_id,
        },
        {
            "profile_id": "p-b",
            "label": "Bot B",
            "bot_id": "bot-b",
            "token": "mock_token_b",
            "chat_id": chat_id,
            "user_id": user_id,
        },
    ]


def _wait_debate_terminal(client: TestClient, debate_id: str, timeout_sec: float = 5.0) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last = {}
    while time.time() < deadline:
        response = client.get(f"/_mock/debate/{debate_id}")
        assert response.status_code == 200
        last = response.json()["result"]
        if str(last.get("status")) in {"completed", "stopped", "failed"}:
            return last
        time.sleep(0.05)
    return last


def _make_client(
    tmp_path: Path,
    *,
    sender_factory: Callable[[MockMessengerStore], Callable[[str, int, int, str], Any]],
) -> tuple[TestClient, MockMessengerStore]:
    store = MockMessengerStore(
        db_path=str(tmp_path / "debate-api.db"),
        data_dir=str(tmp_path / "debate-api-data"),
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
    app.state.debate_orchestrator.set_send_message_handler(sender_factory(store))
    return TestClient(app), store


def test_debate_start_active_stop_and_complete_flow(tmp_path: Path) -> None:
    def sender_factory(store: MockMessengerStore):
        async def fake_sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
            store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
            if not text.startswith("/"):
                store.store_bot_message(
                    token=token,
                    chat_id=chat_id,
                    text="[1][12:00:00][assistant_message] 주장: A\n반박: B\n질문: C",
                )
                store.store_bot_message(
                    token=token,
                    chat_id=chat_id,
                    text='[1][12:00:01][turn_completed] {"status":"success"}',
                )
            return {"ok": True}

        return fake_sender

    client, store = _make_client(tmp_path, sender_factory=sender_factory)
    with client:
        started = client.post(
            "/_mock/debate/start",
            json={
                "topic": "AI coding debate",
                "profiles": _profiles_payload(),
                "rounds": 1,
                "max_turn_sec": 10,
                "fresh_session": True,
            },
        )
        assert started.status_code == 200
        payload = started.json()["result"]
        debate_id = str(payload["debate_id"])

        terminal = _wait_debate_terminal(client, debate_id)
        assert terminal["status"] == "completed"
        assert len(terminal["turns"]) == 2
        assert all(turn["status"] == "success" for turn in terminal["turns"])

        active = client.get("/_mock/debate/active")
        assert active.status_code == 200
        assert active.json()["result"] is None

    store.close()


def test_debate_stop_endpoint_changes_status(tmp_path: Path) -> None:
    def sender_factory(store: MockMessengerStore):
        async def fake_sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
            store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
            if text.startswith("/"):
                store.store_bot_message(token=token, chat_id=chat_id, text="ok")
            return {"ok": True}

        return fake_sender

    client, store = _make_client(tmp_path, sender_factory=sender_factory)
    with client:
        started = client.post(
            "/_mock/debate/start",
            json={
                "topic": "stop test",
                "profiles": _profiles_payload(chat_id=2001),
                "rounds": 1,
                "max_turn_sec": 10,
                "fresh_session": True,
            },
        )
        assert started.status_code == 200
        debate_id = str(started.json()["result"]["debate_id"])

        stop = client.post(f"/_mock/debate/{debate_id}/stop")
        assert stop.status_code == 200
        assert stop.json()["ok"] is True

        terminal = _wait_debate_terminal(client, debate_id, timeout_sec=3.0)
        assert terminal["status"] == "stopped"

    store.close()


def test_debate_start_rejects_duplicate_active_debate(tmp_path: Path) -> None:
    def sender_factory(store: MockMessengerStore):
        async def fake_sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
            store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
            return {"ok": True}

        return fake_sender

    client, store = _make_client(tmp_path, sender_factory=sender_factory)
    with client:
        first = client.post(
            "/_mock/debate/start",
            json={
                "topic": "first debate",
                "profiles": _profiles_payload(chat_id=3001),
                "rounds": 1,
                "max_turn_sec": 10,
                "fresh_session": True,
            },
        )
        assert first.status_code == 200
        first_id = str(first.json()["result"]["debate_id"])

        second = client.post(
            "/_mock/debate/start",
            json={
                "topic": "second debate",
                "profiles": _profiles_payload(chat_id=3001),
                "rounds": 1,
                "max_turn_sec": 10,
                "fresh_session": True,
            },
        )
        assert second.status_code == 409

        # Different scope (different chat_id participants) can run in parallel.
        third = client.post(
            "/_mock/debate/start",
            json={
                "topic": "third debate",
                "profiles": _profiles_payload(chat_id=3002),
                "rounds": 1,
                "max_turn_sec": 10,
                "fresh_session": True,
            },
        )
        assert third.status_code == 200

        stop = client.post(f"/_mock/debate/{first_id}/stop")
        assert stop.status_code == 200

    store.close()


def test_debate_start_validation_errors(tmp_path: Path) -> None:
    def sender_factory(_store: MockMessengerStore):
        async def fake_sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
            return {"ok": True}

        return fake_sender

    client, store = _make_client(tmp_path, sender_factory=sender_factory)
    with client:
        too_few = client.post(
            "/_mock/debate/start",
            json={"topic": "invalid", "profiles": _profiles_payload()[:1], "rounds": 1, "max_turn_sec": 10},
        )
        assert too_few.status_code == 422 or too_few.status_code == 400

        mismatch_profiles = _profiles_payload()
        mismatch_profiles[0]["token"] = "wrong-token"
        mismatch = client.post(
            "/_mock/debate/start",
            json={"topic": "invalid", "profiles": mismatch_profiles, "rounds": 1, "max_turn_sec": 10},
        )
        assert mismatch.status_code == 400
        assert "token mismatch" in mismatch.json()["detail"]

    store.close()
