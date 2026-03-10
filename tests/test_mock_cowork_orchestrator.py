from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from telegram_bot_new.mock_messenger.cowork import CoworkOrchestrator, TurnOutcome
from telegram_bot_new.mock_messenger.schemas import CoworkProfileRef, CoworkStartRequest
from telegram_bot_new.mock_messenger.store import MockMessengerStore


ARTIFACT_DIR_RE = re.compile(r"이번 코워크 결과 경로:\s*(.+)")


@pytest.fixture(autouse=True)
def _legacy_web_fallback_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COWORK_WEB_ALLOW_DETERMINISTIC_FALLBACK", "1")


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


def _artifact_dir_from_prompt(text: str) -> Path | None:
    match = ARTIFACT_DIR_RE.search(str(text or ""))
    if not match:
        return None
    return Path(match.group(1).strip())


def _write_real_landing_artifact(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        "\n".join(
            [
                "<!DOCTYPE html>",
                "<html lang=\"ko\">",
                "  <head>",
                "    <meta charset=\"UTF-8\" />",
                "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />",
                "    <title>프리미엄 플라워 스토어</title>",
                "    <meta name=\"description\" content=\"온라인 주문 전환을 위한 프리미엄 꽃집 랜딩 페이지\" />",
                "    <link rel=\"stylesheet\" href=\"styles.css\" />",
                "  </head>",
                "  <body>",
                "    <main>",
                "      <section id=\"hero\"><h1>오늘 배송 가능한 플라워 컬렉션</h1><p>신뢰감 있는 톤으로 빠르게 주문을 유도합니다.</p><a href=\"#cta\">지금 시작하기</a></section>",
                "      <section id=\"product\"><h2>베스트 셀러</h2><p>상품 신뢰 포인트와 가격대를 함께 제시합니다.</p></section>",
                "      <section id=\"trust\"><h2>구매 신뢰 요소</h2><p>당일 배송, 리뷰, 교환 정책을 한 번에 보여줍니다.</p></section>",
                "      <section id=\"cta\"><h2>주문 시작</h2><p>배송지 입력 후 결제를 진행하세요.</p></section>",
                "    </main>",
                "  </body>",
                "</html>",
            ]
        ),
        encoding="utf-8",
    )
    (root / "styles.css").write_text(
        "\n".join(
            [
                ":root { color-scheme: light; }",
                "body { margin: 0; font-family: 'Helvetica Neue', sans-serif; background: #f6f2eb; color: #1d1d1d; }",
                "main { display: grid; gap: 24px; padding: 24px; }",
                "section { padding: 24px; border-radius: 20px; background: #fffdf9; box-shadow: 0 10px 30px rgba(0,0,0,0.08); }",
                "@media (min-width: 768px) { main { grid-template-columns: repeat(2, minmax(0, 1fr)); } #hero, #cta { grid-column: 1 / -1; } }",
                "@media (min-width: 1440px) { body { font-size: 18px; } main { max-width: 1280px; margin: 0 auto; } }",
            ]
        ),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# 프리미엄 플라워 스토어\n\n- Entry: `index.html`\n- Notes: 실제 implementer가 생성한 랜딩 페이지 산출물\n",
        encoding="utf-8",
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
async def test_cowork_orchestrator_fails_on_invalid_planning_and_preserves_role_normalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COWORK_MAX_PLANNING_ATTEMPTS", "1")
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
            store.store_bot_message(token=token, chat_id=chat_id, text="[1][12:00:00][assistant_message] invalid planning")
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
    assert done["status"] == "failed"
    assert done["tasks"] == []
    assert planner_attempts == 1
    participant_roles = [row["role"] for row in done["participants"]]
    assert "implementer" in participant_roles
    assert done["final_report"] is None
    planning_stage = next(row for row in done["stages"] if str(row.get("stage_type")) == "planning")
    assert planning_stage["resolved_status"] == "failed"
    assert planning_stage["raw_outcome_status"] == "success"

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_retries_planning_with_prompt_proposal_until_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COWORK_WEB_ALLOW_DETERMINISTIC_FALLBACK", "0")
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-planning-retry.db"),
        data_dir=str(tmp_path / "cowork-planning-retry-data"),
    )
    planner_attempts = {"count": 0}

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            planner_attempts["count"] += 1
            if planner_attempts["count"] == 1:
                body = '{"planning_tasks":[{"id":"T1","title":"초안"}]}'
            else:
                body = json.dumps(
                    {
                        "planning_tasks": [
                            {
                                "id": "T1",
                                "title": "실제 산출물 구현",
                                "goal": "랜딩 페이지 파일 생성",
                                "done_criteria": "index.html/styles.css/README.md 생성",
                                "risk": "파일 누락",
                                "owner_role": "implementer",
                                "parallel_group": "G1",
                                "dependencies": [],
                                "artifacts": ["index.html", "styles.css", "README.md"],
                                "estimated_hours": 1.0,
                            }
                        ],
                        "prd_path": "PRD.md",
                        "trd_path": "TRD.md",
                        "db_path": "DB.md",
                        "test_strategy_path": "test_strategy.md",
                        "release_plan_path": "release_plan.md",
                        "design_doc_path": "design_spec.md",
                        "qa_plan_path": "qa_test_plan.md",
                        "prd_content": "# PRD\n- 목표\n- 사용자\n- CTA",
                        "trd_content": "# TRD\n- 구조\n- 파일\n- 배포",
                        "db_content": "# DB\n- 없음\n- 정적 페이지",
                        "test_strategy_content": "# Test\n- 링크 확인\n- 반응형 확인",
                        "release_plan_content": "# Release\n- 로컬 검증\n- 결과 공유",
                        "design_doc_content": "# Design\n- hero/product/trust/cta",
                        "qa_plan_content": "# QA\n- index.html 존재\n- CTA 노출",
                    },
                    ensure_ascii=False,
                )
        elif "검토 대상 planning_tasks" in text:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        elif "implementer" in lowered:
            artifact_dir = _artifact_dir_from_prompt(text)
            assert artifact_dir is not None
            _write_real_landing_artifact(artifact_dir)
            body = (
                "결과요약: 실제 랜딩 페이지 파일 생성 완료\n"
                "검증: index.html, styles.css, README.md 생성 확인\n"
                "실행링크: 없음\n"
                "증빙: 결과 경로 파일 생성\n"
                "테스트요청: CTA 문구와 메타태그 확인\n"
                "남은이슈: 없음"
            )
        elif "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        else:
            body = (
                "최종결론: 실행 가능\n"
                "실행체크리스트: 파일 생성 및 CTA 확인\n"
                "실행링크: 없음\n"
                "증빙요약: artifact 경로 확인\n"
                "즉시실행항목(Top3): 1) 미리보기 확인 2) 카피 검토 3) 공유"
            )
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    started = await orchestrator.start_cowork(request=_make_request(task="프롬프트 재제안 플래닝 테스트"), participants=[
        {"profile_id":"p-a","label":"Bot A","bot_id":"bot-a","token":"token-a","chat_id":1001,"user_id":9001,"role":"controller","adapter":"gemini"},
        {"profile_id":"p-b","label":"Bot B","bot_id":"bot-b","token":"token-b","chat_id":1001,"user_id":9001,"role":"planner","adapter":"codex"},
        {"profile_id":"p-c","label":"Bot C","bot_id":"bot-c","token":"token-c","chat_id":1001,"user_id":9001,"role":"implementer","adapter":"claude"},
    ])
    cowork_id = str(started["cowork_id"])
    done = await _wait_terminal(orchestrator, cowork_id)
    assert done["status"] == "completed"
    assert planner_attempts["count"] == 2
    planning_prompts = [row for row in done["stages"] if str(row.get("stage_type")) == "planning"]
    assert len(planning_prompts) >= 2
    proposal_path = Path.cwd() / "result" / "test-project" / cowork_id / "planning" / "prompt_proposal_round_2.md"
    assert proposal_path.is_file()

    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_orchestrator_default_auto_repair_runs_multiple_rounds_before_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COWORK_WEB_ALLOW_DETERMINISTIC_FALLBACK", "0")
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-auto-repair.db"),
        data_dir=str(tmp_path / "cowork-auto-repair-data"),
    )
    counters = {"controller": 0, "implementer": 0, "qa": 0}

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = json.dumps(
                {
                    "planning_tasks": [
                        {
                            "id": "T1",
                            "title": "웹 랜딩 구현",
                            "goal": "실 결과물 생성",
                            "done_criteria": "실행 가능한 웹 artifact와 링크 확보",
                            "risk": "링크 누락",
                            "owner_role": "implementer",
                            "parallel_group": "G1",
                            "dependencies": [],
                            "artifacts": ["index.html", "styles.css", "README.md"],
                            "estimated_hours": 1.0,
                        }
                    ],
                    "prd_path": "PRD.md",
                    "trd_path": "TRD.md",
                    "db_path": "DB.md",
                    "test_strategy_path": "test_strategy.md",
                    "release_plan_path": "release_plan.md",
                    "design_doc_path": "design_spec.md",
                    "qa_plan_path": "qa_test_plan.md",
                    "prd_content": "# PRD\n- 랜딩 페이지",
                    "trd_content": "# TRD\n- 정적 HTML/CSS",
                    "db_content": "# DB\n- 없음",
                    "test_strategy_content": "# Test\n- 링크 확인",
                    "release_plan_content": "# Release\n- artifact 공유",
                    "design_doc_content": "# Design\n- hero/product/trust/cta",
                    "qa_plan_content": "# QA\n- 링크/CTA/섹션 확인",
                },
                ensure_ascii=False,
            )
        elif "검토 대상 planning_tasks" in text:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        elif "implementer" in lowered:
            counters["implementer"] += 1
            artifact_dir = _artifact_dir_from_prompt(text)
            assert artifact_dir is not None
            _write_real_landing_artifact(artifact_dir)
            if counters["implementer"] < 3:
                body = (
                    "결과요약: 랜딩 페이지 파일 수정 완료\n"
                    "검증: 파일 생성 완료\n"
                    "실행링크: 없음\n"
                    "증빙: 결과 경로 파일 생성\n"
                    "테스트요청: 링크와 CTA 재검토\n"
                    "남은이슈: 실행링크 미기재"
                )
            else:
                body = (
                    "결과요약: 랜딩 페이지와 실행 링크 보강 완료\n"
                    "검증: 파일 생성 및 링크 기재 완료\n"
                    "실행링크: http://127.0.0.1:9082/_mock/preview/landing\n"
                    "증빙: 결과 경로 파일 생성 및 링크 확인\n"
                    "테스트요청: CTA와 링크 동작 확인\n"
                    "남은이슈: 없음"
                )
        elif "integrator" in lowered:
            counters["qa"] += 1
            if counters["qa"] < 3:
                body = "QA결론: FAIL\n결함요약: 링크와 증빙 보강 필요\n재현절차: 결과 열기 후 링크 확인\n수정요청: 링크/증빙 재제출\nQA승인: REJECTED"
            else:
                body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        else:
            counters["controller"] += 1
            body = (
                "최종결론: 실행 가능\n"
                "실행체크리스트: 링크와 파일 검증 완료\n"
                "실행링크: http://127.0.0.1:9082/_mock/preview/landing\n"
                "증빙요약: 링크와 파일 모두 확인\n"
                "즉시실행항목(Top3): 1) 공유 2) 회귀테스트 3) 배포"
            )
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(store=store, send_user_message=sender, poll_interval_sec=0.02, cool_down_sec=0.0)
    orchestrator._is_web_artifact_authoritative_mode = lambda **kwargs: False  # type: ignore[assignment]
    started = await orchestrator.start_cowork(request=_make_request(task="다중 자동 수정 라운드 테스트"), participants=[
        {"profile_id":"p-a","label":"Bot A","bot_id":"bot-a","token":"token-a","chat_id":1001,"user_id":9001,"role":"controller","adapter":"gemini"},
        {"profile_id":"p-b","label":"Bot B","bot_id":"bot-b","token":"token-b","chat_id":1001,"user_id":9001,"role":"planner","adapter":"codex"},
        {"profile_id":"p-c","label":"Bot C","bot_id":"bot-c","token":"token-c","chat_id":1001,"user_id":9001,"role":"implementer","adapter":"claude"},
    ])
    cowork_id = str(started["cowork_id"])
    done = await _wait_terminal(orchestrator, cowork_id)
    assert done["status"] == "completed"
    assert str(done["final_report"]["completion_status"]) == "passed"
    assert counters["implementer"] >= 3
    assert counters["qa"] >= 3
    rework_stages = [row for row in done["stages"] if str(row.get("stage_type")) == "rework"]
    assert len(rework_stages) >= 2
    proposal_path = Path.cwd() / "result" / "test-project" / cowork_id / "implementation" / "prompt_proposal_rework_round_2.md"
    assert proposal_path.is_file()

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
async def test_cowork_controller_reject_uses_soft_gate_and_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COWORK_WEB_ALLOW_PLANNER_AUGMENT", "1")
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-soft-gate.db"),
        data_dir=str(tmp_path / "cowork-soft-gate-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = json.dumps(
                {
                    "planning_tasks": [
                        {
                            "id": "T1",
                            "title": "화면 구현",
                            "goal": "랜딩 페이지 구조 생성",
                            "done_criteria": "index.html/styles.css 생성",
                            "risk": "누락",
                            "owner_role": "implementer",
                            "parallel_group": "G1",
                            "dependencies": [],
                            "artifacts": ["index.html", "styles.css"],
                            "estimated_hours": 1.0,
                        },
                        {
                            "id": "T2",
                            "title": "검증",
                            "goal": "artifact audit 준비",
                            "done_criteria": "README 포함",
                            "risk": "검증 누락",
                            "owner_role": "implementer",
                            "parallel_group": "G2",
                            "dependencies": ["T1"],
                            "artifacts": ["README.md"],
                            "estimated_hours": 0.5,
                        },
                    ],
                    "prd_content": "# PRD\n\n- non-empty",
                    "trd_content": "# TRD\n\n- non-empty",
                    "db_content": "# DB\n\n- non-empty",
                    "test_strategy_content": "# Test Strategy\n\n- non-empty",
                    "release_plan_content": "# Release Plan\n\n- non-empty",
                    "design_doc_content": "# Design Spec\n\n- non-empty",
                    "qa_plan_content": "# QA Test Plan\n\n- non-empty",
                },
                ensure_ascii=False,
            )
        elif "검토 대상 planning_tasks" in lowered:
            body = '{"decision":"REJECTED","reason":"controller wants stronger constraints","must_fix":["constraints"]}'
        elif "qa 리포트" in lowered:
            body = "최종결론: 실행 가능\n실행체크리스트: artifact 확인\n실행링크: 없음\n증빙요약: artifact route\n즉시실행항목(Top3): 1) 리뷰 2) QA 3) 배포"
        elif "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        else:
            body = "결과요약: 구현 완료\n검증: 완료조건 충족\n실행링크: 없음\n증빙: artifact 생성\n테스트요청: index.html 확인\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "soft-gate-artifacts",
    )
    req = _make_request(task="랜딩 페이지 MVP 구현")
    started = await orchestrator.start_cowork(request=req, participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "completed"
    assert snapshot["final_report"]["planning_gate_status"] == "soft_pass"
    assert snapshot["final_report"]["entry_artifact_url"]
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_planning_timeout_fails_without_fallback_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-planning-fallback.db"),
        data_dir=str(tmp_path / "cowork-planning-fallback-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "검토 대상 planning_tasks" in lowered:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        elif "qa 리포트" in lowered:
            body = "최종결론: 실행 가능\n실행체크리스트: artifact 확인\n실행링크: 없음\n증빙요약: artifact route\n즉시실행항목(Top3): 1) 리뷰 2) QA 3) 배포"
        elif "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        else:
            body = "결과요약: 구현 완료\n검증: 완료조건 충족\n실행링크: 없음\n증빙: artifact 생성\n테스트요청: index.html 확인\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "planning-fallback-artifacts",
    )

    original = orchestrator._run_turn_with_recovery

    async def fake_run_turn_with_recovery(*, cowork_id: str, participant: dict[str, Any], prompt_text: str, max_turn_sec: int, **kwargs: Any) -> TurnOutcome:
        if "당신은 멀티봇 협업의 Planner입니다." in prompt_text:
            return TurnOutcome(done=True, status="timeout", detail="timeout", error_text="turn timeout")
        return await original(
            cowork_id=cowork_id,
            participant=participant,
            prompt_text=prompt_text,
            max_turn_sec=max_turn_sec,
            **kwargs,
        )

    monkeypatch.setattr(orchestrator, "_run_turn_with_recovery", fake_run_turn_with_recovery)
    started = await orchestrator.start_cowork(request=_make_request(task="SEO 기본 세팅 페이지 구현"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "failed"
    assert snapshot["final_report"] is None
    planning_stage = next(row for row in snapshot["stages"] if str(row.get("stage_type")) == "planning")
    assert planning_stage["resolved_status"] == "failed"
    assert planning_stage["raw_outcome_status"] == "timeout"
    assert snapshot["last_timeout_event"]["bot_id"] == "bot-b"
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_web_guaranteed_mode_still_runs_planner_and_records_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COWORK_MAX_PLANNING_ATTEMPTS", "1")
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-web-guaranteed.db"),
        data_dir=str(tmp_path / "cowork-web-guaranteed-data"),
    )
    planner_prompts = 0

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        nonlocal planner_prompts
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        if "planner" in text.lower():
            planner_prompts += 1
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:00][assistant_message] ignored')
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "web-guaranteed-artifacts",
    )
    started = await orchestrator.start_cowork(request=_make_request(task="랜딩 페이지 MVP 구현"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "failed"
    assert planner_prompts == 1
    assert snapshot["budget_floor_sec"] == 150
    planning_stage = next(row for row in snapshot["stages"] if str(row.get("stage_type")) == "planning")
    assert planning_stage["raw_outcome_status"] == "success"
    assert planning_stage["resolved_status"] == "failed"
    assert snapshot["final_report"] is None
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_web_strict_mode_fails_when_implementer_does_not_materialize_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COWORK_WEB_ALLOW_DETERMINISTIC_FALLBACK", raising=False)
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-web-strict-fail.db"),
        data_dir=str(tmp_path / "cowork-web-strict-fail-data"),
    )

    planning_body = json.dumps(
        {
            "planning_tasks": [
                {
                    "id": "T1",
                    "title": "랜딩 페이지 구현",
                    "goal": "실제 landing artifact 생성",
                    "done_criteria": "index.html/styles.css/README.md 생성",
                    "risk": "파일 미생성",
                    "owner_role": "implementer",
                    "parallel_group": "G1",
                    "dependencies": [],
                    "artifacts": ["index.html", "styles.css", "README.md"],
                    "estimated_hours": 1.0,
                }
            ],
            "prd_content": "# PRD\n\n- non-empty",
            "trd_content": "# TRD\n\n- non-empty",
            "db_content": "# DB\n\n- non-empty",
            "test_strategy_content": "# Test Strategy\n\n- non-empty",
            "release_plan_content": "# Release Plan\n\n- non-empty",
            "design_doc_content": "# Design Spec\n\n- non-empty",
            "qa_plan_content": "# QA Test Plan\n\n- non-empty",
        },
        ensure_ascii=False,
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = planning_body
        elif "검토 대상 planning_tasks" in lowered:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        else:
            body = "결과요약: 구현 완료\n검증: 완료조건 충족\n실행링크: 없음\n증빙: 문서 검토\n테스트요청: index.html 확인\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "web-strict-fail-artifacts",
    )
    started = await orchestrator.start_cowork(request=_make_request(task="랜딩 페이지 MVP 구현"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "failed"
    assert snapshot["budget_floor_sec"] > 30
    implementation_task = next(row for row in snapshot["tasks"] if int(row.get("task_no") or 0) == 1)
    assert implementation_task["raw_outcome_status"] == "success"
    assert implementation_task["status"] == "failed"
    assert "실제 산출물 파일이 생성되지 않았습니다" in str(implementation_task.get("error_text") or "")
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_web_strict_mode_accepts_materialized_artifact_even_if_turn_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COWORK_WEB_ALLOW_DETERMINISTIC_FALLBACK", raising=False)
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-web-strict-materialized-timeout.db"),
        data_dir=str(tmp_path / "cowork-web-strict-materialized-timeout-data"),
    )

    planning_body = json.dumps(
        {
            "planning_tasks": [
                {
                    "id": "T1",
                    "title": "랜딩 페이지 구현",
                    "goal": "실제 landing artifact 생성",
                    "done_criteria": "index.html/styles.css/README.md 생성",
                    "risk": "파일 미생성",
                    "owner_role": "implementer",
                    "parallel_group": "G1",
                    "dependencies": [],
                    "artifacts": ["index.html", "styles.css", "README.md"],
                    "estimated_hours": 1.0,
                }
            ],
            "prd_content": "# PRD\n\n- non-empty",
            "trd_content": "# TRD\n\n- non-empty",
            "db_content": "# DB\n\n- non-empty",
            "test_strategy_content": "# Test Strategy\n\n- non-empty",
            "release_plan_content": "# Release Plan\n\n- non-empty",
            "design_doc_content": "# Design Spec\n\n- non-empty",
            "qa_plan_content": "# QA Test Plan\n\n- non-empty",
        },
        ensure_ascii=False,
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = planning_body
        elif "검토 대상 planning_tasks" in lowered:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        elif "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        elif "qa 리포트" in lowered:
            body = "최종결론: 실행 가능\n실행체크리스트: artifact 확인\n실행링크: 없음\n증빙요약: artifact route\n즉시실행항목(Top3): 1) 리뷰 2) QA 3) 배포"
        else:
            body = "결과요약: 구현 완료\n검증: 완료조건 충족\n실행링크: 없음\n증빙: artifact 생성\n테스트요청: index.html 확인\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "web-strict-materialized-timeout-artifacts",
    )

    original = orchestrator._run_turn_with_recovery

    async def fake_run_turn_with_recovery(*, cowork_id: str, participant: dict[str, Any], prompt_text: str, max_turn_sec: int, **kwargs: Any) -> TurnOutcome:
        if "당신은 멀티봇 협업의 Implementer입니다." in prompt_text:
            artifact_dir = _artifact_dir_from_prompt(prompt_text)
            assert artifact_dir is not None
            _write_real_landing_artifact(artifact_dir)
            return TurnOutcome(done=True, status="timeout", detail="timeout", error_text="turn timeout", effective_timeout_sec=180)
        return await original(
            cowork_id=cowork_id,
            participant=participant,
            prompt_text=prompt_text,
            max_turn_sec=max_turn_sec,
            **kwargs,
        )

    monkeypatch.setattr(orchestrator, "_run_turn_with_recovery", fake_run_turn_with_recovery)
    started = await orchestrator.start_cowork(request=_make_request(task="랜딩 페이지 MVP 구현"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "completed"
    assert snapshot["final_report"]["completion_status"] == "passed"
    assert snapshot["tasks"][0]["status"] == "success"
    assert snapshot["tasks"][0]["raw_outcome_status"] == "timeout"
    artifact_path = Path(orchestrator.resolve_artifact_path(str(started["cowork_id"]), "index.html") or "")
    assert artifact_path.is_file()
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_web_strict_mode_completes_with_agent_authored_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COWORK_WEB_ALLOW_DETERMINISTIC_FALLBACK", raising=False)
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-web-strict-pass.db"),
        data_dir=str(tmp_path / "cowork-web-strict-pass-data"),
    )

    planning_body = json.dumps(
        {
            "planning_tasks": [
                {
                    "id": "T1",
                    "title": "랜딩 페이지 구현",
                    "goal": "실제 landing artifact 생성",
                    "done_criteria": "index.html/styles.css/README.md 생성",
                    "risk": "파일 미생성",
                    "owner_role": "implementer",
                    "parallel_group": "G1",
                    "dependencies": [],
                    "artifacts": ["index.html", "styles.css", "README.md"],
                    "estimated_hours": 1.0,
                }
            ],
            "prd_content": "# PRD\n\n- non-empty",
            "trd_content": "# TRD\n\n- non-empty",
            "db_content": "# DB\n\n- non-empty",
            "test_strategy_content": "# Test Strategy\n\n- non-empty",
            "release_plan_content": "# Release Plan\n\n- non-empty",
            "design_doc_content": "# Design Spec\n\n- non-empty",
            "qa_plan_content": "# QA Test Plan\n\n- non-empty",
        },
        ensure_ascii=False,
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = planning_body
        elif "검토 대상 planning_tasks" in lowered:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        elif "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        elif "qa 리포트" in lowered:
            body = "최종결론: 실행 가능\n실행체크리스트: artifact 확인 완료\n실행링크: 없음\n증빙요약: 실제 파일 생성 확인\n즉시실행항목(Top3): 1) 리뷰 2) QA 3) 배포"
        else:
            artifact_dir = _artifact_dir_from_prompt(text)
            assert artifact_dir is not None
            _write_real_landing_artifact(artifact_dir)
            body = "결과요약: 실제 랜딩 페이지 구현 완료\n검증: 필수 파일 생성 및 확인\n실행링크: 없음\n증빙: index.html/styles.css/README.md 작성\n테스트요청: artifact route로 열기\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "web-strict-pass-artifacts",
    )
    started = await orchestrator.start_cowork(request=_make_request(task="랜딩 페이지 MVP 구현"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "completed"
    assert snapshot["budget_floor_sec"] > 30
    assert snapshot["final_report"]["scaffold_source"] == "agent"
    assert snapshot["final_report"]["completion_status"] == "passed"
    artifact_path = Path(orchestrator.resolve_artifact_path(str(started["cowork_id"]), "index.html") or "")
    assert artifact_path.is_file()
    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert "Runnable Cowork Artifact" not in artifact_text
    assert "Generated by cowork deterministic web scaffold." not in artifact_text
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_planning_timeout_records_timeout_actor_before_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-planning-timeout-actor.db"),
        data_dir=str(tmp_path / "cowork-planning-timeout-actor-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        elif "qa 리포트" in lowered:
            body = "최종결론: 실행 가능\n실행체크리스트: artifact 확인\n실행링크: 없음\n증빙요약: artifact route\n즉시실행항목(Top3): 1) 리뷰 2) QA 3) 배포"
        else:
            body = "결과요약: 구현 완료\n검증: 완료조건 충족\n실행링크: 없음\n증빙: artifact 생성\n테스트요청: index.html 확인\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "planning-timeout-actor-artifacts",
    )

    async def fake_run_turn_with_recovery(*, cowork_id: str, participant: dict[str, Any], prompt_text: str, max_turn_sec: int, **kwargs: Any) -> TurnOutcome:
        if "당신은 멀티봇 협업의 Planner입니다." in prompt_text:
            return TurnOutcome(done=True, status="timeout", detail="timeout", error_text="turn timeout", effective_timeout_sec=75)
        return TurnOutcome(
            done=True,
            status="success",
            detail="assistant_message",
            response_text="QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
            if "Integrator" in prompt_text
            else "최종결론: 실행 가능\n실행체크리스트: artifact 확인\n실행링크: 없음\n증빙요약: artifact route\n즉시실행항목(Top3): 1) 리뷰 2) QA 3) 배포",
        )

    monkeypatch.setattr(orchestrator, "_run_turn_with_recovery", fake_run_turn_with_recovery)
    started = await orchestrator.start_cowork(request=_make_request(task="SEO 기본 세팅 페이지 구현"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "failed"
    planning_stage = next(row for row in snapshot["stages"] if str(row.get("stage_type")) == "planning")
    assert planning_stage["raw_outcome_status"] == "timeout"
    assert planning_stage["fallback_applied"] is False
    assert snapshot["last_timeout_event"]["origin"] == "turn_timeout"
    assert snapshot["last_timeout_event"]["label"] == "Bot B"
    assert snapshot["last_timeout_event"]["role"] == "planner"
    assert snapshot["last_timeout_event"]["stage_type"] == "planning"
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_stop_reason_and_runner_timeout_event_are_exposed(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-stop-metadata.db"),
        data_dir=str(tmp_path / "cowork-stop-metadata-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        await asyncio.sleep(0.2)
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:00][assistant_message] busy')
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "stop-metadata-artifacts",
    )
    started = await orchestrator.start_cowork(request=_make_request(task="일반 협업 작업"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    cowork_id = str(started["cowork_id"])
    await orchestrator.stop_cowork(
        cowork_id,
        reason="case_timeout",
        source="cowork-web-live-suite",
        requested_by="playwright",
    )
    snapshot = await _wait_terminal(orchestrator, cowork_id, timeout_sec=4.0)
    assert snapshot["status"] == "stopped"
    assert snapshot["stop_reason"] == "case_timeout"
    assert snapshot["stop_source"] == "cowork-web-live-suite"
    assert snapshot["last_timeout_event"]["origin"] == "runner_case_timeout"
    assert snapshot["last_timeout_event"]["label"] == "cowork-web-live-suite"
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_implementation_timeout_recovers_with_scaffold_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-impl-fallback.db"),
        data_dir=str(tmp_path / "cowork-impl-fallback-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = json.dumps(
                {
                    "planning_tasks": [
                        {
                            "id": "T1",
                            "title": "다크모드 구현",
                            "goal": "theme toggle 페이지 생성",
                            "done_criteria": "localStorage 유지",
                            "risk": "상태 누락",
                            "owner_role": "implementer",
                            "parallel_group": "G1",
                            "dependencies": [],
                            "artifacts": ["index.html", "styles.css", "app.js"],
                            "estimated_hours": 1.0,
                        },
                        {
                            "id": "T2",
                            "title": "검증",
                            "goal": "artifact 확인",
                            "done_criteria": "README 반영",
                            "risk": "검증 누락",
                            "owner_role": "implementer",
                            "parallel_group": "G2",
                            "dependencies": ["T1"],
                            "artifacts": ["README.md"],
                            "estimated_hours": 0.5,
                        },
                    ],
                    "prd_content": "# PRD\n\n- non-empty",
                    "trd_content": "# TRD\n\n- non-empty",
                    "db_content": "# DB\n\n- non-empty",
                    "test_strategy_content": "# Test Strategy\n\n- non-empty",
                    "release_plan_content": "# Release Plan\n\n- non-empty",
                    "design_doc_content": "# Design Spec\n\n- non-empty",
                    "qa_plan_content": "# QA Test Plan\n\n- non-empty",
                },
                ensure_ascii=False,
            )
        elif "검토 대상 planning_tasks" in lowered:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        elif "qa 리포트" in lowered:
            body = "최종결론: 실행 가능\n실행체크리스트: artifact 확인\n실행링크: 없음\n증빙요약: artifact route\n즉시실행항목(Top3): 1) 리뷰 2) QA 3) 배포"
        elif "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        else:
            body = "결과요약: 구현 완료\n검증: 완료조건 충족\n실행링크: 없음\n증빙: artifact 생성\n테스트요청: index.html 확인\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "implementation-fallback-artifacts",
    )
    monkeypatch.setattr(orchestrator, "_is_web_guaranteed_mode", lambda **kwargs: False)

    original = orchestrator._run_turn_with_recovery

    async def fake_run_turn_with_recovery(*, cowork_id: str, participant: dict[str, Any], prompt_text: str, max_turn_sec: int, **kwargs: Any) -> TurnOutcome:
        if "당신은 멀티봇 협업의 Implementer입니다." in prompt_text:
            return TurnOutcome(done=True, status="timeout", detail="timeout", error_text="turn timeout")
        return await original(
            cowork_id=cowork_id,
            participant=participant,
            prompt_text=prompt_text,
            max_turn_sec=max_turn_sec,
            **kwargs,
        )

    monkeypatch.setattr(orchestrator, "_run_turn_with_recovery", fake_run_turn_with_recovery)
    started = await orchestrator.start_cowork(request=_make_request(task="다크모드 토글 페이지 구현"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "completed"
    assert snapshot["final_report"]["scaffold_source"] in {"fallback", "hybrid"}
    assert any("fallback_scaffold" in str(task.get("response_text") or "") for task in snapshot["tasks"])
    execution_stage = next(row for row in snapshot["stages"] if str(row.get("stage_type")) == "implementation")
    execution_task = next(row for row in snapshot["tasks"] if int(row.get("task_no") or 0) == 1)
    assert execution_stage["raw_outcome_status"] == "timeout"
    assert execution_stage["fallback_applied"] is True
    assert execution_task["raw_outcome_status"] == "timeout"
    assert execution_task["fallback_applied"] is True
    assert snapshot["last_timeout_event"]["origin"] == "turn_timeout"
    assert snapshot["last_timeout_event"]["label"] == "Bot C"
    assert snapshot["last_timeout_event"]["role"] == "implementer"
    assert snapshot["last_timeout_event"]["stage_type"] == "implementation"
    await orchestrator.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_cowork_qa_and_finalization_timeout_use_synthesized_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-qa-final-fallback.db"),
        data_dir=str(tmp_path / "cowork-qa-final-fallback-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = json.dumps(
                {
                    "planning_tasks": [
                        {
                            "id": "T1",
                            "title": "SEO landing",
                            "goal": "semantic html scaffold 생성",
                            "done_criteria": "meta/og 포함",
                            "risk": "seo 누락",
                            "owner_role": "implementer",
                            "parallel_group": "G1",
                            "dependencies": [],
                            "artifacts": ["index.html", "styles.css"],
                            "estimated_hours": 1.0,
                        },
                        {
                            "id": "T2",
                            "title": "검증",
                            "goal": "artifact 확인",
                            "done_criteria": "README 반영",
                            "risk": "검증 누락",
                            "owner_role": "implementer",
                            "parallel_group": "G2",
                            "dependencies": ["T1"],
                            "artifacts": ["README.md"],
                            "estimated_hours": 0.5,
                        },
                    ],
                    "prd_content": "# PRD\n\n- non-empty",
                    "trd_content": "# TRD\n\n- non-empty",
                    "db_content": "# DB\n\n- non-empty",
                    "test_strategy_content": "# Test Strategy\n\n- non-empty",
                    "release_plan_content": "# Release Plan\n\n- non-empty",
                    "design_doc_content": "# Design Spec\n\n- non-empty",
                    "qa_plan_content": "# QA Test Plan\n\n- non-empty",
                },
                ensure_ascii=False,
            )
        elif "검토 대상 planning_tasks" in lowered:
            body = '{"decision":"APPROVED","reason":"ok","must_fix":[]}'
        else:
            body = "결과요약: 구현 완료\n검증: 완료조건 충족\n실행링크: 없음\n증빙: artifact 생성\n테스트요청: index.html 확인\n남은이슈: 없음"
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "qa-final-fallback-artifacts",
    )

    original = orchestrator._run_turn_with_recovery

    async def fake_run_turn_with_recovery(*, cowork_id: str, participant: dict[str, Any], prompt_text: str, max_turn_sec: int, **kwargs: Any) -> TurnOutcome:
        lowered = prompt_text.lower()
        if "당신은 멀티봇 협업의 integrator입니다." in lowered or "당신은 멀티봇 협업의 controller입니다." in lowered and "qa 리포트" in lowered:
            return TurnOutcome(done=True, status="timeout", detail="timeout", error_text="turn timeout")
        return await original(
            cowork_id=cowork_id,
            participant=participant,
            prompt_text=prompt_text,
            max_turn_sec=max_turn_sec,
            **kwargs,
        )

    monkeypatch.setattr(orchestrator, "_run_turn_with_recovery", fake_run_turn_with_recovery)
    started = await orchestrator.start_cowork(request=_make_request(task="SEO 기본 세팅 페이지 구현"), participants=[
        {"profile_id": "p-a", "label": "Bot A", "bot_id": "bot-a", "token": "token-a", "chat_id": 1001, "user_id": 9001, "role": "controller", "adapter": "codex"},
        {"profile_id": "p-b", "label": "Bot B", "bot_id": "bot-b", "token": "token-b", "chat_id": 1001, "user_id": 9001, "role": "planner", "adapter": "codex"},
        {"profile_id": "p-c", "label": "Bot C", "bot_id": "bot-c", "token": "token-c", "chat_id": 1001, "user_id": 9001, "role": "implementer", "adapter": "codex"},
    ])
    snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
    assert snapshot["status"] == "completed"
    assert snapshot["final_report"]["qa_signoff"] == "APPROVED"
    assert snapshot["final_report"]["entry_artifact_url"]
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
    assert str(done["final_report"]["entry_artifact_url"]).endswith("/artifact/index.html")
    assert len(done["tasks"]) >= 1

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
    assert done["status"] == "completed"
    assert str(done["final_report"]["completion_status"]) == "passed"
    assert str(done["final_report"]["entry_artifact_url"]).endswith("/artifact/index.html")
    failures = done["final_report"]["quality_gate_failures"]
    assert failures == []

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
