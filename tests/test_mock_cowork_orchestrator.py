from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from telegram_bot_new.mock_messenger.cowork import CoworkOrchestrator, TurnOutcome
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


def _scenario(task: str) -> dict[str, Any]:
    return {
        "project_id": "test-project",
        "objective": task,
        "brand_tone": "신뢰감 있는 프리미엄",
        "target_audience": "일반 사용자",
        "core_cta": "지금 시작하기",
        "required_sections": ["hero", "product", "trust", "cta"],
        "forbidden_elements": ["허위 과장 문구"],
        "constraints": ["예산/기간/품질 제약 준수"],
        "deadline": "2026-03-31",
        "priority": "P1",
    }


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
        scenario=_scenario(task),
    )


def _plan_task_line(
    *,
    task_id: str,
    title: str,
    goal: str,
    done_criteria: str,
    risk: str,
    parallel_group: str = "G1",
    dependencies: list[str] | None = None,
    owner_role: str = "implementer",
    artifacts: list[str] | None = None,
    estimated_hours: float = 1.0,
) -> str:
    return json.dumps(
        {
            "id": task_id,
            "title": title,
            "goal": goal,
            "done_criteria": done_criteria,
            "risk": risk,
            "owner_role": owner_role,
            "parallel_group": parallel_group,
            "dependencies": dependencies or [],
            "artifacts": artifacts or ["design_spec.md"],
            "estimated_hours": estimated_hours,
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_cowork_start_creates_artifact_workspace_and_sets_project_command(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-project-sync.db"),
        data_dir=str(tmp_path / "cowork-project-sync-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}

        lowered = text.lower()
        if "검토 대상 planning_tasks" in text:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        elif "planner" in lowered:
            body = "\n".join(
                [
                    _plan_task_line(task_id="T1", title="요구 분석", goal="요구 정리", done_criteria="요구 목록 작성", risk="누락"),
                    _plan_task_line(task_id="T2", title="구현", goal="기능 구현", done_criteria="동작 확인", risk="회귀", parallel_group="G2"),
                ]
            )
        elif "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        elif "qa 리포트" in lowered:
            body = (
                "최종결론: 실행 가능\n"
                "실행체크리스트: 검증 완료\n"
                "실행링크: 없음\n"
                "증빙요약: 로그 확인\n"
                "즉시실행항목(Top3): 1) 테스트 2) 리뷰 3) 배포"
            )
        else:
            body = "결과요약: 완료\n검증: 충족\n실행링크: 없음\n증빙: 로그\n테스트요청: 없음\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    req = _make_request(task="프로젝트 경로 동기화 테스트")
    participants = [
        {
            "profile_id": "p-a",
            "label": "Bot A",
            "bot_id": "bot-a",
            "token": "token-a",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "controller",
            "adapter": "codex",
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
            "role": "implementer",
            "adapter": "codex",
        },
    ]
    artifact_dir: Path | None = None
    project_dir = Path.cwd() / "result" / "test-project"
    try:
        started = await orchestrator.start_cowork(request=req, participants=participants)
        cowork_id = str(started["cowork_id"])
        artifact_dir = Path.cwd() / "result" / "test-project" / cowork_id
        assert artifact_dir.is_dir()

        done = await _wait_terminal(orchestrator, cowork_id)
        assert done["status"] == "completed"

        project_command = f"/project {artifact_dir}"
        for row in participants:
            messages = store.get_messages(token=str(row["token"]), chat_id=int(row["chat_id"]), limit=50)
            assert any(
                message.get("direction") == "user" and str(message.get("text") or "") == project_command
                for message in messages
            )
        assert (artifact_dir / "result.json").is_file()
    finally:
        await orchestrator.shutdown()
        store.close()
        if artifact_dir is not None and artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)
        if project_dir.exists() and not any(project_dir.iterdir()):
            project_dir.rmdir()


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
            body = "\n".join(
                [
                    _plan_task_line(task_id="T1", title="작업 분해", goal="구성", done_criteria="2개 이상", risk="누락"),
                    _plan_task_line(task_id="T2", title="검증 계획", goal="검증 기준 정의", done_criteria="체크리스트 정의", risk="누락", parallel_group="G2"),
                ]
            )
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
async def test_run_turn_with_recovery_extends_timeout_when_turn_is_in_progress(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-timeout-extension.db"),
        data_dir=str(tmp_path / "cowork-timeout-extension-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        lowered = text.strip().lower()
        if lowered == "/stop":
            store.store_bot_message(token=token, chat_id=chat_id, text="Stop requested.")
            return {"ok": True}
        store.store_bot_message(token=token, chat_id=chat_id, text="Queued turn: test-timeout-extension\nsession=s1\nagent=codex")
        store.store_bot_message(
            token=token,
            chat_id=chat_id,
            text="[1][12:00:00][thread_started] {\"thread_id\":\"t1\"}\n[2][12:00:00][turn_started] {}",
        )

        async def _delayed_success() -> None:
            await asyncio.sleep(1.2)
            store.store_bot_message(token=token, chat_id=chat_id, text="[3][12:00:01][assistant_message] 결과요약: 완료")
            store.store_bot_message(token=token, chat_id=chat_id, text='[4][12:00:01][turn_completed] {"status":"success"}')

        asyncio.create_task(_delayed_success())
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    participant = {
        "profile_id": "p-b",
        "label": "Bot B",
        "bot_id": "bot-b",
        "token": "token-b",
        "chat_id": 1002,
        "user_id": 9002,
        "role": "planner",
        "adapter": "codex",
    }
    cowork_id = store.create_cowork(
        task="timeout extension test",
        max_parallel=1,
        max_turn_sec=1,
        fresh_session=False,
        keep_partial_on_error=True,
        participants=[participant],
    )

    outcome = await orchestrator._run_turn_with_recovery(
        cowork_id=cowork_id,
        participant=participant,
        prompt_text="planner timeout extension prompt",
        max_turn_sec=1,
    )
    assert outcome.status == "success"
    assert "결과요약" in str(outcome.response_text or "")

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_stage_execution_uses_run_turn_with_recovery(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-stage-execution-recovery.db"),
        data_dir=str(tmp_path / "cowork-stage-execution-recovery-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    participant = {
        "profile_id": "p-c",
        "label": "Bot C",
        "bot_id": "bot-c",
        "token": "token-c",
        "chat_id": 1003,
        "user_id": 9003,
        "role": "implementer",
        "adapter": "codex",
    }
    cowork_id = store.create_cowork(
        task="execution recovery routing test",
        max_parallel=1,
        max_turn_sec=1,
        fresh_session=False,
        keep_partial_on_error=True,
        participants=[participant],
    )

    orchestrator._planning_meta_cache[cowork_id] = {
        "design_doc_path": "design_spec.md",
        "qa_plan_path": "qa_test_plan.md",
    }

    calls: list[str] = []

    async def fake_run_turn_with_recovery(**kwargs: Any) -> TurnOutcome:
        calls.append(str(kwargs.get("prompt_text") or ""))
        return TurnOutcome(
            done=True,
            status="success",
            detail="assistant_message",
            response_text=(
                "결과요약: 완료\n"
                "검증: 충족\n"
                "실행링크: 없음\n"
                "증빙: 로그\n"
                "테스트요청: 없음\n"
                "남은이슈: 없음"
            ),
        )

    orchestrator._run_turn_with_recovery = fake_run_turn_with_recovery  # type: ignore[assignment]

    plan_items = [
        {
            "id": "T1",
            "title": "실행 작업",
            "goal": "복구 경로 실행",
            "done_criteria": "성공 응답",
            "risk": "타임아웃",
            "owner_role": "implementer",
            "parallel_group": "G1",
            "dependencies": [],
            "artifacts": ["result.md"],
            "estimated_hours": 1.0,
        }
    ]
    role_map = {
        "controller": participant,
        "planner": participant,
        "qa": participant,
        "implementers": [participant],
    }

    rows = await orchestrator._stage_execution(
        cowork_id=cowork_id,
        task_text="execution recovery routing test",
        plan_items=plan_items,
        role_map=role_map,
        max_parallel=1,
        max_turn_sec=1,
        task_no_start=1,
        round_no=1,
    )
    assert rows is not None
    assert calls
    assert any("실행 작업" in prompt for prompt in calls)
    task_rows = store.list_cowork_tasks(cowork_id=cowork_id)
    assert task_rows and str(task_rows[0].get("status")) == "success"

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_uses_planning_fallback_and_role_normalization(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-fallback.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-fallback-data"),
    )

    planner_attempts = 0

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        nonlocal planner_attempts
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if "planner" in text.lower():
            planner_attempts += 1
            if planner_attempts == 1:
                store.store_bot_message(token=token, chat_id=chat_id, text="[1][12:00:00][assistant_message] invalid planning")
            else:
                body = _plan_task_line(
                    task_id="T1",
                    title="fallback task",
                    goal="재계획",
                    done_criteria="스키마 적합",
                    risk="누락",
                )
                store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
                store.store_bot_message(
                    token=token,
                    chat_id=chat_id,
                    text=f"[1][12:00:00][assistant_message] {_plan_task_line(task_id='T2', title='검증', goal='검증', done_criteria='리뷰 통과', risk='오판')}",
                )
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if "integrator" in text.lower():
            body = "통합요약: fallback\n충돌사항: 없음\n누락사항: 없음\n권장수정: 없음"
        elif "검토 대상 planning_tasks" in text.lower():
            body = '{"decision":"APPROVED","reason":"schema and role normalization ok","must_fix":[]}'
        elif "당신은 멀티봇 협업의 controller입니다." in text.lower() and "할당 작업 번호" in text:
            body = "게이트결론: APPROVED\n게이트체크리스트: fallback\n다음조치(Top3): 1) a 2) b 3) c"
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
    assert len(done["tasks"]) >= 1
    assert planner_attempts >= 2
    participant_roles = [row["role"] for row in done["participants"]]
    assert "implementer" in participant_roles

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_blocks_dependent_task_when_predecessor_fails(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-deps.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-deps-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = "\n".join(
                [
                    _plan_task_line(
                        task_id="T1",
                        title="선행 작업",
                        goal="먼저 수행",
                        done_criteria="완료",
                        risk="실패",
                        owner_role="implementer",
                        dependencies=[],
                    ),
                    _plan_task_line(
                        task_id="T2",
                        title="후행 작업",
                        goal="선행 의존",
                        done_criteria="완료",
                        risk="연쇄 실패",
                        owner_role="implementer",
                        dependencies=["T1"],
                    ),
                ]
            )
            store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if "검토 대상 planning_tasks" in lowered:
            store.store_bot_message(
                token=token,
                chat_id=chat_id,
                text='[1][12:00:00][assistant_message] {"decision":"APPROVED","reason":"ok","must_fix":[]}',
            )
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if "할당 작업 번호: 1" in text:
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:00][assistant_message] 실패')
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"error"}')
            return {"ok": True}
        if "integrator" in lowered:
            body = "QA결론: FAIL\n결함요약: 선행 실패\n재현절차: T1 실행\n수정요청: T1 수정\nQA승인: REJECTED"
        elif "qa 리포트" in lowered:
            body = "최종결론: 미완료\n실행체크리스트: 재작업 필요\n즉시실행항목(Top3): 1) T1 수정 2) 재검증 3) 재보고"
        else:
            body = "결과요약: 완료\n검증: 충족\n남은이슈: 없음"
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
    req = _make_request(task="dependency block test")
    participants = [
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
        {"profile_id": "p-d", "label": "Bot D", "bot_id": "bot-d", "token": "token-d", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
        {"profile_id": "p-e", "label": "Bot E", "bot_id": "bot-e", "token": "token-e", "chat_id": 1001, "user_id": 9001, "role": "qa", "adapter": "codex"},
    ]

    started = await orchestrator.start_cowork(request=req, participants=participants)
    cowork_id = str(started["cowork_id"])
    done = await _wait_terminal(orchestrator, cowork_id)
    assert done["status"] == "failed"
    task2 = next((row for row in done["tasks"] if str(row.get("title")) == "후행 작업"), None)
    assert task2 is not None
    assert str(task2.get("status")) == "failed"
    assert "dependency" in str(task2.get("error_text") or "").lower()

    # token-d(후행 담당)에는 실제 구현 프롬프트가 전달되지 않아야 한다.
    token_d_messages = store.get_messages(token="token-d", chat_id=1001, limit=20)
    non_command_user_msgs = [m for m in token_d_messages if m.get("direction") == "user" and not str(m.get("text") or "").startswith("/")]
    assert non_command_user_msgs == []

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_respects_parallel_group_wave_order(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-parallel-group.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-parallel-group-data"),
    )
    state = {"t1_done": False, "group_violation": False}

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = "\n".join(
                [
                    _plan_task_line(
                        task_id="T1",
                        title="g1 task",
                        goal="먼저 처리",
                        done_criteria="완료",
                        risk="순서오류",
                        parallel_group="G1",
                        dependencies=[],
                    ),
                    _plan_task_line(
                        task_id="T2",
                        title="g2 task",
                        goal="다음 웨이브 처리",
                        done_criteria="완료",
                        risk="순서오류",
                        parallel_group="G2",
                        dependencies=[],
                    ),
                ]
            )
        elif "검토 대상 planning_tasks" in lowered:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        elif "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        elif "qa 리포트" in lowered:
            body = (
                "최종결론: 실행 가능\n"
                "실행체크리스트: 점검 완료\n"
                "실행링크: 없음\n"
                "증빙요약: 로그 확인\n"
                "즉시실행항목(Top3): 1) 회귀 2) 리뷰 3) 배포"
            )
        elif "할당 작업 번호: 1" in text:
            await asyncio.sleep(0.05)
            state["t1_done"] = True
            body = "결과요약: T1 완료\n검증: 충족\n실행링크: 없음\n증빙: 로그\n테스트요청: 없음\n남은이슈: 없음"
        elif "할당 작업 번호: 2" in text:
            if not bool(state["t1_done"]):
                state["group_violation"] = True
            body = "결과요약: T2 완료\n검증: 충족\n실행링크: 없음\n증빙: 로그\n테스트요청: 없음\n남은이슈: 없음"
        else:
            body = "결과요약: 완료\n검증: 충족\n실행링크: 없음\n증빙: 로그\n테스트요청: 없음\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    req = _make_request(task="parallel group gate test", max_parallel=2)
    participants = [
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
        {"profile_id": "p-d", "label": "Bot D", "bot_id": "bot-d", "token": "token-d", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
        {"profile_id": "p-e", "label": "Bot E", "bot_id": "bot-e", "token": "token-e", "chat_id": 1001, "user_id": 9001, "role": "qa", "adapter": "codex"},
    ]
    started = await orchestrator.start_cowork(request=req, participants=participants)
    done = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert done["status"] == "completed"
    assert state["group_violation"] is False

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
            body = "\n".join(
                [
                    _plan_task_line(task_id="T1", title="화면 구현", goal="꽃집 랜더링", done_criteria="화면 렌더와 검증", risk="링크 누락"),
                    _plan_task_line(task_id="T2", title="링크 검증", goal="실행 링크 검증", done_criteria="접속 확인", risk="미검증", parallel_group="G2"),
                ]
            )
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
            body = "\n".join(
                [
                    _plan_task_line(task_id="T1", title="화면 구현", goal="꽃집 랜더링", done_criteria="화면 렌더와 검증", risk="링크 누락"),
                    _plan_task_line(task_id="T2", title="링크 점검", goal="실행 링크 준비", done_criteria="링크 제공", risk="누락", parallel_group="G2"),
                ]
            )
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
                    _plan_task_line(task_id="T1", title="작업 1", goal="g1", done_criteria="d1", risk="r1", parallel_group="G1"),
                    _plan_task_line(task_id="T2", title="작업 2", goal="g2", done_criteria="d2", risk="r2", parallel_group="G1"),
                    _plan_task_line(task_id="T3", title="작업 3", goal="g3", done_criteria="d3", risk="r3", parallel_group="G2"),
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
async def test_cowork_orchestrator_auto_fallbacks_gemini_human_input_to_codex(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-orchestrator-gemini-fallback.db"),
        data_dir=str(tmp_path / "cowork-orchestrator-gemini-fallback-data"),
    )
    adapter_state_by_token = {"token-b": "gemini"}
    planner_commands: list[str] = []

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        lowered = text.lower()
        if token == "token-b" and text.startswith("/"):
            planner_commands.append(text)
            if lowered.startswith("/mode codex"):
                adapter_state_by_token[token] = "codex"
            if lowered.startswith("/stop"):
                store.store_bot_message(token=token, chat_id=chat_id, text="stop requested.")
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}

        if "planner" in lowered:
            if adapter_state_by_token.get(token) == "gemini":
                store.store_bot_message(
                    token=token,
                    chat_id=chat_id,
                    text="[1][12:00:00][error] Gemini requires human input: open browser and sign in.",
                )
                store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"error"}')
                return {"ok": True}
            body = _plan_task_line(
                task_id="T1",
                title="핵심 작업",
                goal="기능 구현",
                done_criteria="동작 확인",
                risk="누락",
            )
        elif "integrator" in lowered:
            body = "통합요약: 통합 완료\n충돌사항: 없음\n누락사항: 없음\n권장수정: 없음"
        elif "controller" in lowered:
            body = "최종결론: 실행 가능\n실행체크리스트: 검증 완료\n즉시실행항목(Top3): 1) 테스트 2) 리뷰 3) 배포"
        else:
            body = "결과요약: 구현 완료\n검증: 충족\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    cowork_id = store.create_cowork(
        task="계약 보강 테스트",
        max_parallel=1,
        max_turn_sec=10,
        fresh_session=True,
        keep_partial_on_error=True,
        participants=[
            {
                "profile_id": "p-b",
                "label": "Bot B",
                "bot_id": "bot-b",
                "token": "token-b",
                "chat_id": 1001,
                "user_id": 9001,
                "role": "planner",
                "adapter": "gemini",
            }
        ],
    )
    store.set_cowork_running(cowork_id=cowork_id)
    participant = {
        "profile_id": "p-b",
        "label": "Bot B",
        "bot_id": "bot-b",
        "token": "token-b",
        "chat_id": 1001,
        "user_id": 9001,
        "role": "planner",
        "adapter": "gemini",
    }
    outcome = await orchestrator._retry_turn_with_provider_fallback(
        cowork_id=cowork_id,
        participant=participant,
        prompt_text="당신은 멀티봇 협업의 Planner입니다.\n테스트",
        max_turn_sec=2,
        fallback_provider="codex",
        fallback_model="gpt-5",
    )
    assert outcome is not None
    assert outcome.status == "success"
    assert participant["adapter"] == "codex"
    assert any(cmd.startswith("/mode codex") for cmd in planner_commands)
    assert any(cmd.startswith("/model gpt-5") for cmd in planner_commands)

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
            body = "\n".join(
                [
                    _plan_task_line(task_id="T1", title="요구사항 정리", goal="요약", done_criteria="정리본 작성", risk="누락"),
                    _plan_task_line(task_id="T2", title="검토 기준 작성", goal="완료 기준 명시", done_criteria="체크리스트 작성", risk="누락", parallel_group="G2"),
                ]
            )
        elif "검토 대상 planning_tasks" in text:
            body = '{"decision":"APPROVED","reason":"planning review ok","must_fix":[]}'
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
