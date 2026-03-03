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


@pytest.mark.asyncio
async def test_cowork_orchestrator_render_task_reworks_until_link_present(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-render.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-render-data"),
    )
    counters = {"controller": 0}

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}

        lowered = text.lower()
        if "planner" in lowered:
            body = '{"title":"화면 구현","goal":"꽃집 랜더링","done_criteria":"화면 렌더와 검증","risk":"링크 누락"}'
        elif "integrator" in lowered:
            body = "통합요약: 통합 완료\n충돌사항: 없음\n누락사항: 링크 재확인\n권장수정: 실행링크 제출\n증빙링크: 없음"
        elif "controller" in lowered:
            counters["controller"] += 1
            if counters["controller"] == 1:
                body = (
                    "최종결론: 조건부 완료\n"
                    "실행체크리스트: 링크 보강 필요\n"
                    "실행링크: 없음\n"
                    "증빙요약: 링크 누락\n"
                    "즉시실행항목(Top3): 1) 링크보강 2) 재검증 3) 승인"
                )
            else:
                body = (
                    "최종결론: 실행 가능\n"
                    "실행체크리스트: 링크 확인 완료\n"
                    "실행링크: http://127.0.0.1:9082/flower-shop\n"
                    "증빙요약: 브라우저 접속 확인\n"
                    "즉시실행항목(Top3): 1) 회귀테스트 2) 리뷰 3) 배포"
                )
        else:
            if "[보강 라운드" in text:
                body = (
                    "결과요약: 링크 증빙 보강\n"
                    "검증: 충족\n"
                    "실행링크: http://127.0.0.1:9082/flower-shop\n"
                    "남은이슈: 없음"
                )
            else:
                body = "결과요약: 초안 구현\n검증: 일부 충족\n실행링크: 없음\n남은이슈: 링크 미제출"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    req = _make_request(task="꽃집 랜더링 페이지 만들어줘")
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
    done = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert done["status"] == "completed"
    assert str(done["final_report"]["completion_status"]) == "passed"
    assert str(done["final_report"]["execution_link"]).startswith("http://127.0.0.1:9082")
    assert len(done["tasks"]) >= 2

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_render_task_fails_when_link_missing(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-render-fail.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-render-fail-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = '{"title":"화면 구현","goal":"꽃집 랜더링","done_criteria":"화면 렌더와 검증","risk":"링크 누락"}'
        elif "integrator" in lowered:
            body = "통합요약: 통합 완료\n충돌사항: 없음\n누락사항: 링크 누락\n권장수정: 링크 제출\n증빙링크: 없음"
        elif "controller" in lowered:
            body = (
                "최종결론: 조건부 완료\n"
                "실행체크리스트: 링크 필요\n"
                "실행링크: 없음\n"
                "증빙요약: 링크 누락\n"
                "즉시실행항목(Top3): 1) 링크 2) 검증 3) 승인"
            )
        else:
            body = "결과요약: 구현\n검증: 일부 충족\n실행링크: 없음\n남은이슈: 링크 미제출"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        max_rework_rounds=1,
    )
    req = _make_request(task="꽃집 랜더링 페이지 만들어줘")
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
    done = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert done["status"] == "failed"
    assert "quality gate failed" in str(done.get("error_summary") or "")
    failures = done["final_report"]["quality_gate_failures"]
    assert any("실행 가능한 링크" in row for row in failures)

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_serializes_execution_per_bot_chat(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-serialization.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-serialization-data"),
    )
    in_flight_by_scope: dict[tuple[str, int], int] = {}
    overlaps = 0

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        nonlocal overlaps
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}

        if text.startswith("당신은 멀티봇 협업의 Planner입니다."):
            body = "\n".join(
                [
                    '{"title":"작업 1","goal":"g1","done_criteria":"d1","risk":"r1"}',
                    '{"title":"작업 2","goal":"g2","done_criteria":"d2","risk":"r2"}',
                    '{"title":"작업 3","goal":"g3","done_criteria":"d3","risk":"r3"}',
                ]
            )
        elif text.startswith("당신은 멀티봇 협업의 Integrator입니다."):
            body = "통합요약: 통합 완료\n충돌사항: 없음\n누락사항: 없음\n권장수정: 없음"
        elif text.startswith("당신은 멀티봇 협업의 Controller입니다."):
            body = "최종결론: 실행 가능\n실행체크리스트: 점검 완료\n즉시실행항목(Top3): 1) a 2) b 3) c"
        else:
            scope = (token, int(chat_id))
            current = in_flight_by_scope.get(scope, 0)
            if current > 0:
                overlaps += 1
            in_flight_by_scope[scope] = current + 1
            await asyncio.sleep(0.05)
            in_flight_by_scope[scope] = max(0, in_flight_by_scope[scope] - 1)
            body = "결과요약: 구현 완료\n검증: 충족\n실행링크: http://127.0.0.1:9082/test\n남은이슈: 없음"

        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    req = _make_request(task="executor serialization test", max_parallel=3)
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
            "role": "integrator",
            "adapter": "claude",
        },
        {
            "profile_id": "p-b-exec",
            "label": "Bot B Executor",
            "bot_id": "bot-b",
            "token": "token-b",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "executor",
            "adapter": "codex",
        },
    ]
    started = await orchestrator.start_cowork(request=req, participants=participants)
    done = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert done["status"] == "completed"
    assert overlaps == 0

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_fails_when_final_verdict_is_incomplete(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-verdict-fail.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-verdict-fail-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if text.startswith("당신은 멀티봇 협업의 Planner입니다."):
            body = '{"title":"요구사항 정리","goal":"요약","done_criteria":"정리본 작성","risk":"누락"}'
        elif text.startswith("당신은 멀티봇 협업의 Integrator입니다."):
            body = "통합요약: 산출물 점검 완료\n충돌사항: 없음\n누락사항: 없음\n권장수정: 없음"
        elif text.startswith("당신은 멀티봇 협업의 Controller입니다."):
            body = (
                "최종결론: 요구사항 미이행 상태\n"
                "실행체크리스트: 추가 구현 필요\n"
                "즉시실행항목(Top3): 1) 구현 2) 검증 3) 재검토"
            )
        else:
            body = "결과요약: 초안 작성\n검증: 일부 충족\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        max_rework_rounds=0,
    )
    req = _make_request(task="문서 초안 작성")
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
    done = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert done["status"] == "failed"
    failures = [str(row) for row in done["final_report"]["quality_gate_failures"]]
    assert any("미완료/미이행" in row for row in failures)

    await orchestrator.shutdown()
    store.close()
