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
                "    default_role: controller",
                "    webhook:",
                "      path_secret: bot-a-path",
                "      secret_token: bot-a-secret",
                "  - bot_id: bot-b",
                "    name: Bot B",
                "    mode: embedded",
                "    telegram_token: mock_token_b",
                "    adapter: codex",
                "    default_role: planner",
                "    webhook:",
                "      path_secret: bot-b-path",
                "      secret_token: bot-b-secret",
                "  - bot_id: bot-c",
                "    name: Bot C",
                "    mode: embedded",
                "    telegram_token: mock_token_c",
                "    adapter: claude",
                "    default_role: executor",
                "    webhook:",
                "      path_secret: bot-c-path",
                "      secret_token: bot-c-secret",
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
            "role": "controller",
        },
        {
            "profile_id": "p-b",
            "label": "Bot B",
            "bot_id": "bot-b",
            "token": "mock_token_b",
            "chat_id": chat_id,
            "user_id": user_id,
            "role": "planner",
        },
        {
            "profile_id": "p-c",
            "label": "Bot C",
            "bot_id": "bot-c",
            "token": "mock_token_c",
            "chat_id": chat_id,
            "user_id": user_id,
            "role": "executor",
        },
    ]


def _wait_cowork_terminal(client: TestClient, cowork_id: str, timeout_sec: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last: dict[str, Any] = {}
    while time.time() < deadline:
        response = client.get(f"/_mock/cowork/{cowork_id}")
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
        db_path=str(tmp_path / "cowork-api.db"),
        data_dir=str(tmp_path / "cowork-api-data"),
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
    app.state.cowork_orchestrator.set_send_message_handler(sender_factory(store))
    return TestClient(app), store


def test_cowork_start_active_stop_and_complete_flow(tmp_path: Path) -> None:
    def sender_factory(store: MockMessengerStore):
        async def fake_sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
            store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
            if text.startswith("/"):
                store.store_bot_message(token=token, chat_id=chat_id, text="[1][12:00:00][turn_completed] {\"status\":\"success\"}")
                return {"ok": True}

            lowered = text.lower()
            if "planner" in lowered:
                reply = "\n".join(
                    [
                        '{"title":"요구사항 정리","goal":"요구사항 구조화","done_criteria":"핵심 조건 3개","risk":"누락 가능성"}',
                        '{"title":"API 설계","goal":"엔드포인트 제안","done_criteria":"스키마 정의","risk":"호환성"}',
                    ]
                )
            elif "integrator" in lowered:
                reply = "통합요약: 결과 통합 완료\n충돌사항: 없음\n누락사항: 없음\n권장수정: 문서화"
            elif "controller" in lowered:
                reply = "최종결론: 계획 실행 가능\n실행체크리스트: 1) 검증 2) 배포 3) 모니터링\n즉시실행항목(Top3): 1) 테스트 2) 리뷰 3) 릴리즈"
            else:
                reply = "결과요약: 작업 완료\n검증: 완료조건 충족\n남은이슈: 없음"

            store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {reply}")
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}

        return fake_sender

    client, store = _make_client(tmp_path, sender_factory=sender_factory)
    with client:
        started = client.post(
            "/_mock/cowork/start",
            json={
                "task": "대시보드 기능 개선",
                "profiles": _profiles_payload(),
                "max_parallel": 2,
                "max_turn_sec": 10,
                "fresh_session": True,
                "keep_partial_on_error": True,
            },
        )
        assert started.status_code == 200
        cowork_id = str(started.json()["result"]["cowork_id"])

        terminal = _wait_cowork_terminal(client, cowork_id)
        assert terminal["status"] == "completed"
        assert len(terminal["tasks"]) >= 1
        assert isinstance(terminal["final_report"], dict)
        assert terminal["final_report"]["final_conclusion"]

        active = client.get("/_mock/cowork/active")
        assert active.status_code == 200
        assert active.json()["result"] is None

    store.close()


def test_cowork_start_rejects_duplicate_active(tmp_path: Path) -> None:
    def sender_factory(store: MockMessengerStore):
        async def fake_sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
            store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
            return {"ok": True}

        return fake_sender

    client, store = _make_client(tmp_path, sender_factory=sender_factory)
    with client:
        first = client.post(
            "/_mock/cowork/start",
            json={
                "task": "first task",
                "profiles": _profiles_payload(chat_id=3001),
                "max_parallel": 2,
                "max_turn_sec": 10,
                "fresh_session": True,
            },
        )
        assert first.status_code == 200
        cowork_id = str(first.json()["result"]["cowork_id"])

        second = client.post(
            "/_mock/cowork/start",
            json={
                "task": "second task",
                "profiles": _profiles_payload(chat_id=3002),
                "max_parallel": 2,
                "max_turn_sec": 10,
                "fresh_session": True,
            },
        )
        assert second.status_code == 409

        stop = client.post(f"/_mock/cowork/{cowork_id}/stop")
        assert stop.status_code == 200
    store.close()


def test_cowork_validation_and_role_update_endpoint(tmp_path: Path) -> None:
    def sender_factory(_store: MockMessengerStore):
        async def fake_sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
            return {"ok": True}

        return fake_sender

    client, store = _make_client(tmp_path, sender_factory=sender_factory)
    with client:
        too_few = client.post(
            "/_mock/cowork/start",
            json={
                "task": "invalid",
                "profiles": _profiles_payload()[:1],
                "max_parallel": 2,
                "max_turn_sec": 10,
            },
        )
        assert too_few.status_code in {400, 422}

        bad_profiles = _profiles_payload()
        bad_profiles[0]["token"] = "wrong"
        mismatch = client.post(
            "/_mock/cowork/start",
            json={
                "task": "invalid",
                "profiles": bad_profiles,
                "max_parallel": 2,
                "max_turn_sec": 10,
            },
        )
        assert mismatch.status_code == 400
        assert "token mismatch" in mismatch.json()["detail"]

        role_update = client.post("/_mock/bot_catalog/role", json={"bot_id": "bot-b", "role": "integrator"})
        assert role_update.status_code == 200
        assert role_update.json()["result"]["bot"]["default_role"] == "integrator"

        missing_role = client.post("/_mock/bot_catalog/role", json={"bot_id": "bot-x", "role": "planner"})
        assert missing_role.status_code == 404

    store.close()
