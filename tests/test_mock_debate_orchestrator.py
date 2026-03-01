from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from telegram_bot_new.mock_messenger.debate import DebateOrchestrator
from telegram_bot_new.mock_messenger.store import MockMessengerStore


def _participants(chat_id: int = 1001, user_id: int = 9001) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": "p-a",
            "label": "Bot A",
            "bot_id": "bot-a",
            "token": "token-a",
            "chat_id": chat_id,
            "user_id": user_id,
            "adapter": "gemini",
        },
        {
            "profile_id": "p-b",
            "label": "Bot B",
            "bot_id": "bot-b",
            "token": "token-b",
            "chat_id": chat_id,
            "user_id": user_id,
            "adapter": "codex",
        },
    ]


def _request(*, topic: str, rounds: int, max_turn_sec: int, fresh_session: bool = True) -> Any:
    return SimpleNamespace(
        topic=topic,
        rounds=rounds,
        max_turn_sec=max_turn_sec,
        fresh_session=fresh_session,
    )


async def _wait_terminal(orchestrator: DebateOrchestrator, debate_id: str, timeout_sec: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        snapshot = orchestrator.get_debate_snapshot(debate_id)
        if snapshot and str(snapshot.get("status")) in {"completed", "stopped", "failed"}:
            return snapshot
        await asyncio.sleep(0.05)
    snapshot = orchestrator.get_debate_snapshot(debate_id)
    assert snapshot is not None
    return snapshot


@pytest.mark.asyncio
async def test_orchestrator_round_robin_order(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "debate-orchestrator-order.db"),
        data_dir=str(tmp_path / "debate-orchestrator-order-data"),
    )
    turn_tokens: list[str] = []

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text="ok")
            return {"ok": True}
        turn_tokens.append(token)
        response_text = "주장: A\n반박: B\n질문: C"
        if "최종 라운드" in text:
            response_text = "요약: 핵심 쟁점 정리\n결론: 최종 결론"
        store.store_bot_message(
            token=token,
            chat_id=chat_id,
            text=f"[1][12:00:00][assistant_message] {response_text}",
        )
        store.store_bot_message(
            token=token,
            chat_id=chat_id,
            text='[1][12:00:01][turn_completed] {"status":"success"}',
        )
        return {"ok": True}

    orchestrator = DebateOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    started = await orchestrator.start_debate(
        request=_request(topic="round robin", rounds=2, max_turn_sec=1),
        participants=_participants(),
    )
    debate_id = str(started["debate_id"])
    done = await _wait_terminal(orchestrator, debate_id)

    assert done["status"] == "completed"
    # round1: A -> B, final round(2): starter(A) synthesis only
    assert turn_tokens == ["token-a", "token-b", "token-a"]
    assert len(done["turns"]) == 3
    assert "요약:" in str(done["turns"][-1]["prompt_text"])
    assert "결론:" in str(done["turns"][-1]["prompt_text"])
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_orchestrator_continues_after_timeout_and_error(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "debate-orchestrator-failures.db"),
        data_dir=str(tmp_path / "debate-orchestrator-failures-data"),
    )
    turn_count = 0

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        nonlocal turn_count
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            return {"ok": True}
        turn_count += 1
        if turn_count == 2:
            store.store_bot_message(token=token, chat_id=chat_id, text="[1][12:00:00][error] forced error")
            return {"ok": True}
        if turn_count >= 3:
            response_text = "주장: A\n반박: B\n질문: C"
            if "최종 라운드" in text:
                response_text = "요약: 핵심 요약\n결론: 최종 결론"
            store.store_bot_message(
                token=token,
                chat_id=chat_id,
                text=f"[1][12:00:00][assistant_message] {response_text}",
            )
            store.store_bot_message(
                token=token,
                chat_id=chat_id,
                text='[1][12:00:01][turn_completed] {"status":"success"}',
            )
        return {"ok": True}

    orchestrator = DebateOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.05, cool_down_sec=0.0)
    started = await orchestrator.start_debate(
        request=_request(topic="failure continue", rounds=2, max_turn_sec=1),
        participants=_participants(chat_id=1201),
    )
    debate_id = str(started["debate_id"])
    done = await _wait_terminal(orchestrator, debate_id, timeout_sec=8.0)

    assert done["status"] == "completed"
    statuses = [str(turn["status"]) for turn in done["turns"]]
    # round1 two turns + final round(2) starter-only one turn
    assert len(statuses) == 3
    assert "timeout" in statuses
    assert "error" in statuses
    assert statuses.count("success") >= 1
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_orchestrator_stop_requested_stops_debate(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "debate-orchestrator-stop.db"),
        data_dir=str(tmp_path / "debate-orchestrator-stop-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        return {"ok": True}

    orchestrator = DebateOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.05, cool_down_sec=0.0)
    started = await orchestrator.start_debate(
        request=_request(topic="stop", rounds=3, max_turn_sec=3),
        participants=_participants(chat_id=1301),
    )
    debate_id = str(started["debate_id"])
    await asyncio.sleep(0.1)
    await orchestrator.stop_debate(debate_id)

    done = await _wait_terminal(orchestrator, debate_id, timeout_sec=5.0)
    assert done["status"] == "stopped"
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_orchestrator_records_template_error(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "debate-orchestrator-template.db"),
        data_dir=str(tmp_path / "debate-orchestrator-template-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            return {"ok": True}
        store.store_bot_message(
            token=token,
            chat_id=chat_id,
            text="[1][12:00:00][assistant_message] 주장: A\n반박: B",
        )
        store.store_bot_message(
            token=token,
            chat_id=chat_id,
            text='[1][12:00:01][turn_completed] {"status":"success"}',
        )
        return {"ok": True}

    orchestrator = DebateOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    started = await orchestrator.start_debate(
        request=_request(topic="template", rounds=1, max_turn_sec=1),
        participants=_participants(chat_id=1401),
    )
    debate_id = str(started["debate_id"])
    done = await _wait_terminal(orchestrator, debate_id)

    assert done["status"] == "completed"
    assert len(done["turns"]) == 2
    assert all(str(turn["status"]) == "template_error" for turn in done["turns"])
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_orchestrator_template_repair_recovers_to_success(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "debate-orchestrator-template-repair.db"),
        data_dir=str(tmp_path / "debate-orchestrator-template-repair-data"),
    )
    per_token_non_command_count: dict[str, int] = {}

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            return {"ok": True}

        count = per_token_non_command_count.get(token, 0) + 1
        per_token_non_command_count[token] = count
        if count == 1:
            # first response misses '질문' and should trigger automatic repair
            store.store_bot_message(
                token=token,
                chat_id=chat_id,
                text="[1][12:00:00][assistant_message] 주장: A\n반박: B",
            )
        else:
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

    orchestrator = DebateOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    started = await orchestrator.start_debate(
        request=_request(topic="template repair", rounds=1, max_turn_sec=6),
        participants=_participants(chat_id=1501),
    )
    debate_id = str(started["debate_id"])
    done = await _wait_terminal(orchestrator, debate_id)

    assert done["status"] == "completed"
    assert len(done["turns"]) == 2
    assert all(str(turn["status"]) == "success" for turn in done["turns"])
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_orchestrator_waits_for_turn_completed_before_success(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "debate-orchestrator-streamed.db"),
        data_dir=str(tmp_path / "debate-orchestrator-streamed-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            return {"ok": True}

        # First chunk is incomplete; completion arrives shortly after.
        store.store_bot_message(
            token=token,
            chat_id=chat_id,
            text="[1][12:00:00][assistant_message] 주장: A",
        )

        async def delayed_completion(*, token_value: str = token, chat_id_value: int = chat_id) -> None:
            await asyncio.sleep(0.08)
            store.store_bot_message(
                token=token_value,
                chat_id=chat_id_value,
                text="[1][12:00:01][assistant_message] 반박: B\n질문: C",
            )
            store.store_bot_message(
                token=token_value,
                chat_id=chat_id_value,
                text='[1][12:00:01][turn_completed] {"status":"success"}',
            )

        asyncio.create_task(delayed_completion())
        return {"ok": True}

    orchestrator = DebateOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    started = await orchestrator.start_debate(
        request=_request(topic="streamed completion", rounds=1, max_turn_sec=2),
        participants=_participants(chat_id=1601),
    )
    debate_id = str(started["debate_id"])
    done = await _wait_terminal(orchestrator, debate_id, timeout_sec=6.0)

    assert done["status"] == "completed"
    assert len(done["turns"]) == 2
    assert all(str(turn["status"]) == "success" for turn in done["turns"])
    await orchestrator.shutdown()
    store.close()
