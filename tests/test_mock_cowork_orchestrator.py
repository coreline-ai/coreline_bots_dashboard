from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from telegram_bot_new.mock_messenger.cowork import CoworkOrchestrator
from telegram_bot_new.mock_messenger.schemas import CoworkProfileRef, CoworkStartRequest
from telegram_bot_new.mock_messenger.store import MockMessengerStore


async def _wait_terminal(orchestrator: CoworkOrchestrator, cowork_id: str, timeout_sec: float = 8.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    snapshot: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        snapshot = orchestrator.get_cowork_snapshot(cowork_id)
        assert snapshot is not None
        if str(snapshot.get("status")) in {"completed", "stopped", "failed"}:
            return snapshot
        await asyncio.sleep(0.05)
    assert snapshot is not None
    return snapshot


def _make_request(*, task: str = "테스트 작업", max_parallel: int = 2, keep_partial_on_error: bool = True) -> CoworkStartRequest:
    profiles = [
        CoworkProfileRef(
            profile_id="p-a",
            label="Bot A",
            bot_id="bot-a",
            token="token-a",
            chat_id=1001,
            user_id=9001,
            role="controller",
        ),
        CoworkProfileRef(
            profile_id="p-b",
            label="Bot B",
            bot_id="bot-b",
            token="token-b",
            chat_id=1001,
            user_id=9001,
            role="planner",
        ),
        CoworkProfileRef(
            profile_id="p-c",
            label="Bot C",
            bot_id="bot-c",
            token="token-c",
            chat_id=1001,
            user_id=9001,
            role="executor",
        ),
    ]
    return CoworkStartRequest(
        task=task,
        profiles=profiles,
        max_parallel=max_parallel,
        max_turn_sec=10,
        fresh_session=True,
        keep_partial_on_error=keep_partial_on_error,
    )


@pytest.mark.asyncio
async def test_cowork_orchestrator_completes_with_final_report(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = '{"title":"작업 분해","goal":"구성","done_criteria":"2개 이상","risk":"누락"}'
        elif "integrator" in lowered:
            body = "통합요약: 통합 완료\n충돌사항: 없음\n누락사항: 없음\n권장수정: 문서화"
        elif "controller" in lowered:
            body = "최종결론: 실행 가능\n실행체크리스트: 검증/배포/모니터링\n즉시실행항목(Top3): 1) 테스트 2) 코드리뷰 3) 배포"
        else:
            body = "결과요약: 완료\n검증: 충족\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    req = _make_request()
    participants = [
        {
            "profile_id": "p-a",
            "label": "Bot A",
            "bot_id": "bot-a",
            "token": "token-a",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "controller",
            "adapter": "gemini",
        },
        {
            "profile_id": "p-b",
            "label": "Bot B",
            "bot_id": "bot-b",
            "token": "token-b",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "planner",
            "adapter": "codex",
        },
        {
            "profile_id": "p-c",
            "label": "Bot C",
            "bot_id": "bot-c",
            "token": "token-c",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "executor",
            "adapter": "claude",
        },
    ]
    started = await orchestrator.start_cowork(request=req, participants=participants)
    cowork_id = str(started["cowork_id"])
    done = await _wait_terminal(orchestrator, cowork_id)
    assert done["status"] == "completed"
    assert len(done["tasks"]) >= 1
    assert isinstance(done["final_report"], dict)
    assert done["final_report"]["final_conclusion"]

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_uses_planning_fallback_and_role_normalization(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-fallback.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-fallback-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if "planner" in text.lower():
            store.store_bot_message(token=token, chat_id=chat_id, text="[1][12:00:00][assistant_message] invalid planning")
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if "integrator" in text.lower():
            body = "통합요약: fallback\n충돌사항: 없음\n누락사항: 없음\n권장수정: 없음"
        elif "controller" in text.lower():
            body = "최종결론: fallback 결론\n실행체크리스트: fallback\n즉시실행항목(Top3): 1) a 2) b 3) c"
        else:
            body = "결과요약: fallback task\n검증: 충족\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    req = _make_request(task="fallback test")
    participants = [
        {
            "profile_id": "p-a",
            "label": "Bot A",
            "bot_id": "bot-a",
            "token": "token-a",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "controller",
            "adapter": "gemini",
        },
        {
            "profile_id": "p-b",
            "label": "Bot B",
            "bot_id": "bot-b",
            "token": "token-b",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "controller",
            "adapter": "codex",
        },
        {
            "profile_id": "p-c",
            "label": "Bot C",
            "bot_id": "bot-c",
            "token": "token-c",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "integrator",
            "adapter": "claude",
        },
    ]
    started = await orchestrator.start_cowork(request=req, participants=participants)
    cowork_id = str(started["cowork_id"])
    done = await _wait_terminal(orchestrator, cowork_id)
    assert done["status"] == "completed"
    assert len(done["tasks"]) == 1
    participant_roles = [row["role"] for row in done["participants"]]
    assert "executor" in participant_roles

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_stop_requested(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-stop.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-stop-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.05, cool_down_sec=0.0)
    req = _make_request(task="stop test")
    participants = [
        {
            "profile_id": "p-a",
            "label": "Bot A",
            "bot_id": "bot-a",
            "token": "token-a",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "controller",
            "adapter": "gemini",
        },
        {
            "profile_id": "p-b",
            "label": "Bot B",
            "bot_id": "bot-b",
            "token": "token-b",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "planner",
            "adapter": "codex",
        },
    ]
    started = await orchestrator.start_cowork(request=req, participants=participants)
    cowork_id = str(started["cowork_id"])
    await orchestrator.stop_cowork(cowork_id)
    done = await _wait_terminal(orchestrator, cowork_id, timeout_sec=4.0)
    assert done["status"] == "stopped"

    await orchestrator.shutdown()
    store.close()
