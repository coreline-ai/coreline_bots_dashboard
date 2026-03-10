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

RESULT_ROOT = Path.cwd() / "result" / "multibot_test_results"


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


def _request_from_participants(task: str, participants: list[dict[str, Any]], *, max_parallel: int = 2) -> CoworkStartRequest:
    profiles: list[CoworkProfileRef] = []
    for row in participants:
        profiles.append(
            CoworkProfileRef(
                profile_id=str(row["profile_id"]),
                label=str(row["label"]),
                bot_id=str(row["bot_id"]),
                token=str(row["token"]),
                chat_id=int(row["chat_id"]),
                user_id=int(row["user_id"]),
                role=str(row["role"]),
            )
        )
    return CoworkStartRequest(
        task=task,
        profiles=profiles,
        max_parallel=max_parallel,
        max_turn_sec=10,
        fresh_session=True,
        keep_partial_on_error=True,
        scenario={
            "project_id": "multibot-output-tests",
            "objective": task,
            "brand_tone": "명확하고 실무 중심",
            "target_audience": "프로덕트 팀",
            "core_cta": "결과물 검토 시작",
            "required_sections": ["overview", "implementation", "qa", "next-actions"],
            "forbidden_elements": ["근거 없는 완료 선언"],
            "constraints": ["검증 가능한 산출물 필수"],
            "deadline": "2026-03-31",
            "priority": "P1",
        },
    )


def _build_participants(*, with_second_executor: bool = False) -> list[dict[str, Any]]:
    base = [
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
    if with_second_executor:
        base.append(
            {
                "profile_id": "p-d",
                "label": "Bot D",
                "bot_id": "bot-d",
                "token": "token-d",
                "chat_id": 1001,
                "user_id": 9001,
                "role": "executor",
                "adapter": "codex",
            }
        )
    return base


def _plan_task_line(
    *,
    task_id: str,
    title: str,
    goal: str,
    done_criteria: str,
    risk: str,
    parallel_group: str = "G1",
) -> str:
    return json.dumps(
        {
            "id": task_id,
            "title": title,
            "goal": goal,
            "done_criteria": done_criteria,
            "risk": risk,
            "owner_role": "implementer",
            "parallel_group": parallel_group,
            "dependencies": [],
            "artifacts": ["design_spec.md"],
            "estimated_hours": 1.0,
        },
        ensure_ascii=False,
    )


def _write_case_result(
    *,
    case_id: str,
    title: str,
    expected: dict[str, Any],
    snapshot: dict[str, Any],
    artifact_payload: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> None:
    case_dir = RESULT_ROOT / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    (case_dir / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    meta_payload = {
        "case_id": case_id,
        "title": title,
        "expected": expected,
        "actual": {
            "status": snapshot.get("status"),
            "cowork_id": snapshot.get("cowork_id"),
            "completion_status": (snapshot.get("final_report") or {}).get("completion_status")
            if isinstance(snapshot.get("final_report"), dict)
            else None,
            "tasks_count": len(snapshot.get("tasks") or []),
            "stages_count": len(snapshot.get("stages") or []),
        },
    }
    if extra:
        meta_payload["extra"] = extra
    (case_dir / "case_meta.json").write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# {case_id} - {title}",
        "",
        f"- expected_status: `{expected.get('status')}`",
        f"- actual_status: `{snapshot.get('status')}`",
        f"- cowork_id: `{snapshot.get('cowork_id')}`",
    ]
    final_report = snapshot.get("final_report") if isinstance(snapshot.get("final_report"), dict) else {}
    if final_report:
        lines.append(f"- completion_status: `{final_report.get('completion_status')}`")
        lines.append(f"- execution_link: `{final_report.get('execution_link')}`")
    lines.append(f"- tasks_count: `{len(snapshot.get('tasks') or [])}`")
    lines.append("")
    lines.append("## Final Report")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(final_report, ensure_ascii=False, indent=2))
    lines.append("```")
    (case_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    if artifact_payload and isinstance(artifact_payload.get("files"), list):
        out_dir = case_dir / "cowork_artifacts"
        out_dir.mkdir(parents=True, exist_ok=True)
        for row in artifact_payload["files"]:
            src = Path(str(row.get("path") or ""))
            if src.is_file():
                shutil.copy2(src, out_dir / src.name)


@pytest.mark.asyncio
async def test_tc01_render_success_generates_case_outputs(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "tc01.db"),
        data_dir=str(tmp_path / "tc01-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "검토 대상 planning_tasks" in text:
            body = '{"decision":"APPROVED","reason":"planning review ok","must_fix":[]}'
        elif "planner" in lowered:
            body = "\n".join(
                [
                    _plan_task_line(
                        task_id="T1",
                        title="화면 구현",
                        goal="꽃집 랜더링",
                        done_criteria="링크 제공",
                        risk="누락",
                    ),
                    _plan_task_line(
                        task_id="T2",
                        title="링크 검증",
                        goal="실행 링크 점검",
                        done_criteria="접속 확인",
                        risk="미검증",
                        parallel_group="G2",
                    ),
                ]
            )
        elif "integrator" in lowered:
            body = "통합요약: 통합 완료\n충돌사항: 없음\n누락사항: 없음\n권장수정: 없음\n증빙링크: http://127.0.0.1:9082/flower-shop"
        elif "controller" in lowered:
            body = (
                "최종결론: 실행 가능\n"
                "실행체크리스트: 링크 확인 완료\n"
                "실행링크: http://127.0.0.1:9082/flower-shop\n"
                "증빙요약: 접속 확인\n"
                "즉시실행항목(Top3): 1) 테스트 2) 리뷰 3) 배포"
            )
        else:
            body = (
                "결과요약: 구현 완료\n"
                "검증: 충족\n"
                "실행링크: http://127.0.0.1:9082/flower-shop\n"
                "증빙: 테스트 로그\n"
                "남은이슈: 없음"
            )
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "tc01-artifacts",
    )
    try:
        participants = _build_participants()
        request = _request_from_participants("꽃집 랜더링 페이지 만들어줘", participants)
        started = await orchestrator.start_cowork(request=request, participants=participants)
        snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
        assert snapshot["status"] == "completed"
        assert str(snapshot["final_report"]["completion_status"]) == "passed"
        assert str(snapshot["final_report"]["entry_artifact_url"]).endswith("/artifact/index.html")
        _write_case_result(
            case_id="TC01_render_success",
            title="Render request should complete with execution link",
            expected={"status": "completed"},
            snapshot=snapshot,
            artifact_payload=orchestrator.get_cowork_artifacts(str(started["cowork_id"])),
        )
    finally:
        await orchestrator.shutdown()
        store.close()


@pytest.mark.asyncio
async def test_tc02_render_missing_link_generates_failure_outputs(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "tc02.db"),
        data_dir=str(tmp_path / "tc02-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "검토 대상 planning_tasks" in text:
            body = '{"decision":"APPROVED","reason":"planning review ok","must_fix":[]}'
        elif "planner" in lowered:
            body = "\n".join(
                [
                    _plan_task_line(
                        task_id="T1",
                        title="화면 구현",
                        goal="꽃집 랜더링",
                        done_criteria="링크 제공",
                        risk="누락",
                    ),
                    _plan_task_line(
                        task_id="T2",
                        title="링크 검증",
                        goal="실행 링크 점검",
                        done_criteria="접속 확인",
                        risk="미검증",
                        parallel_group="G2",
                    ),
                ]
            )
        elif "integrator" in lowered:
            body = "통합요약: 통합 완료\n충돌사항: 없음\n누락사항: 링크 누락\n권장수정: 링크 제출\n증빙링크: 없음"
        elif "controller" in lowered:
            body = (
                "최종결론: 조건부 완료\n"
                "실행체크리스트: 링크 필요\n"
                "실행링크: 없음\n"
                "증빙요약: 링크 없음\n"
                "즉시실행항목(Top3): 1) 링크제출 2) 재검증 3) 승인"
            )
        else:
            body = (
                "결과요약: 구현\n"
                "검증: 일부 충족\n"
                "실행링크: 없음\n"
                "증빙: 없음\n"
                "남은이슈: 링크 누락"
            )
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "tc02-artifacts",
        max_rework_rounds=1,
    )
    try:
        participants = _build_participants()
        request = _request_from_participants("꽃집 랜더링 페이지 만들어줘", participants)
        started = await orchestrator.start_cowork(request=request, participants=participants)
        snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
        assert snapshot["status"] == "completed"
        assert str(snapshot["final_report"]["completion_status"]) == "passed"
        assert str(snapshot["final_report"]["entry_artifact_url"]).endswith("/artifact/index.html")
        _write_case_result(
            case_id="TC02_render_missing_link_failure",
            title="Render request without explicit live link should still pass via artifact route",
            expected={"status": "completed"},
            snapshot=snapshot,
            artifact_payload=orchestrator.get_cowork_artifacts(str(started["cowork_id"])),
        )
    finally:
        await orchestrator.shutdown()
        store.close()


@pytest.mark.asyncio
async def test_tc03_gemini_fallback_generates_case_outputs(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "tc03.db"),
        data_dir=str(tmp_path / "tc03-data"),
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

        if "검토 대상 planning_tasks" in text:
            body = '{"decision":"APPROVED","reason":"planning review ok","must_fix":[]}'
        elif "planner" in lowered:
            if adapter_state_by_token.get(token) == "gemini":
                store.store_bot_message(
                    token=token,
                    chat_id=chat_id,
                    text='[1][12:00:01][turn_completed] {"status":"error","message":"requires human input: open browser and sign in"}',
                )
                return {"ok": True}
            body = "\n".join(
                [
                    _plan_task_line(
                        task_id="T1",
                        title="핵심 구현",
                        goal="fallback 복구",
                        done_criteria="정상 실행",
                        risk="재발",
                    ),
                    _plan_task_line(
                        task_id="T2",
                        title="회귀 점검",
                        goal="fallback 재발 방지",
                        done_criteria="재현 테스트 통과",
                        risk="재발",
                        parallel_group="G2",
                    ),
                ]
            )
        elif "integrator" in lowered:
            body = "통합요약: 통합 완료\n충돌사항: 없음\n누락사항: 없음\n권장수정: 없음\n증빙링크: 없음"
        elif "controller" in lowered:
            body = (
                "최종결론: 실행 가능\n"
                "실행체크리스트: fallback 검증 완료\n"
                "실행링크: 없음\n"
                "증빙요약: provider 전환 로그 확인\n"
                "즉시실행항목(Top3): 1) 모니터링 2) 재현방지 3) 문서화"
            )
        else:
            body = "결과요약: 구현 완료\n검증: 충족\n실행링크: 없음\n증빙: 로그\n남은이슈: 없음"

        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "tc03-artifacts",
    )
    try:
        participants = _build_participants(with_second_executor=True)
        participants[2]["role"] = "integrator"
        participants[1]["adapter"] = "gemini"
        request = _request_from_participants("Gemini fallback 검증 작업", participants)
        started = await orchestrator.start_cowork(request=request, participants=participants)
        snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
        assert snapshot["status"] == "completed"
        assert any(cmd.startswith("/mode codex") for cmd in planner_commands)
        assert any(cmd.startswith("/model gpt-5") for cmd in planner_commands)
        assert snapshot["final_report"]["entry_artifact_url"] in {None, ""}
        _write_case_result(
            case_id="TC03_gemini_human_input_fallback",
            title="Gemini human-input requirement should auto fallback to Codex",
            expected={"status": "completed"},
            snapshot=snapshot,
            artifact_payload=orchestrator.get_cowork_artifacts(str(started["cowork_id"])),
            extra={"planner_commands": planner_commands},
        )
    finally:
        await orchestrator.shutdown()
        store.close()


@pytest.mark.asyncio
async def test_tc04_parallel_4bots_generates_case_outputs(tmp_path: Path) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / "tc04.db"),
        data_dir=str(tmp_path / "tc04-data"),
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
                    _plan_task_line(task_id="T1", title="작업 1", goal="g1", done_criteria="d1", risk="r1", parallel_group="G1"),
                    _plan_task_line(task_id="T2", title="작업 2", goal="g2", done_criteria="d2", risk="r2", parallel_group="G1"),
                    _plan_task_line(task_id="T3", title="작업 3", goal="g3", done_criteria="d3", risk="r3", parallel_group="G2"),
                ]
            )
        elif "integrator" in lowered:
            body = "통합요약: 4봇 분업 완료\n충돌사항: 없음\n누락사항: 없음\n권장수정: 없음\n증빙링크: 없음"
        elif "controller" in lowered:
            body = (
                "최종결론: 실행 가능\n"
                "실행체크리스트: 4봇 분업 검증 완료\n"
                "실행링크: 없음\n"
                "증빙요약: 태스크 3건 처리 확인\n"
                "즉시실행항목(Top3): 1) 회귀테스트 2) 문서화 3) 배포 준비"
            )
        else:
            assignee = "Bot D" if "bot-d" in token else "Bot C"
            body = (
                f"결과요약: {assignee} 작업 완료\n"
                "검증: 충족\n"
                "실행링크: 없음\n"
                "증빙: 테스트 로그\n"
                "남은이슈: 없음"
            )
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "tc04-artifacts",
    )
    try:
        participants = _build_participants(with_second_executor=True)
        request = _request_from_participants("4봇 분업 테스트", participants, max_parallel=2)
        started = await orchestrator.start_cowork(request=request, participants=participants)
        snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
        assert snapshot["status"] == "completed"
        assert len(snapshot.get("tasks") or []) >= 3
        _write_case_result(
            case_id="TC04_parallel_4bots",
            title="4-bot parallel-ready execution should produce task outputs",
            expected={"status": "completed"},
            snapshot=snapshot,
            artifact_payload=orchestrator.get_cowork_artifacts(str(started["cowork_id"])),
        )
    finally:
        await orchestrator.shutdown()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task", "project_id", "expected_profile"),
    [
        ("랜딩 페이지 MVP 구현: hero/benefits/CTA 섹션 포함, index.html styles.css 생성", "web-cowork-r2-01-landing-page-mvp", "landing-basic"),
        ("반응형 랜딩 페이지 구현: 390/768/1440 뷰포트 대응과 검증 로그 포함", "web-cowork-r2-02-390-768-1440", "landing-responsive"),
        ("문의 폼 페이지 구현: 입력 검증/오류 메시지/성공 상태", "web-cowork-r2-03-form-validation", "form-validation"),
        ("다크모드 토글 페이지 구현: localStorage 유지", "web-cowork-r2-04-theme-toggle", "theme-toggle"),
        ("접근성 우선 페이지 구현: skip link, aria, keyboard navigation", "web-cowork-r2-05-accessibility", "accessibility-page"),
        ("상태 관리 데모 페이지 구현: 탭/카운터/토스트 상태 동기화", "web-cowork-r2-06-state-demo", "state-demo"),
        ("상품 카탈로그 필터 페이지 구현: 검색/카테고리/정렬", "web-cowork-r2-07-catalog-filter", "catalog-filter"),
        ("다국어 랜딩 페이지 구현: ko/en 전환 및 문자열 리소스 분리", "web-cowork-r2-08-ko-en", "i18n-landing"),
        ("SEO 랜딩 페이지 구현: meta title/description/og 태그 포함", "web-cowork-r2-09-seo", "seo-landing"),
        ("배포 전 스모크 테스트 패키지: 주요 버튼/링크/폼/네비 점검 보고서 작성", "web-cowork-r2-10-cowork-project", "smoke-pack"),
    ],
)
async def test_tc05_web_fallback_profiles_complete_with_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task: str,
    project_id: str,
    expected_profile: str,
) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / f"{project_id}.db"),
        data_dir=str(tmp_path / f"{project_id}-data"),
    )

    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=user_id, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "integrator" in lowered:
            body = "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED"
        elif "controller" in lowered:
            body = (
                "최종결론: 실행 가능\n"
                "실행체크리스트: artifact 검증 완료\n"
                "실행링크: 없음\n"
                "증빙요약: artifact route 확인\n"
                "즉시실행항목(Top3): 1) 리뷰 2) QA 3) 배포"
            )
        else:
            body = (
                "결과요약: 구현 완료\n"
                "검증: 완료조건 충족\n"
                "실행링크: 없음\n"
                "증빙: artifact 생성\n"
                "남은이슈: 없음"
            )
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True}

    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / "tc05-artifacts",
    )

    original = orchestrator._run_turn_with_recovery

    async def fake_run_turn_with_recovery(
        *,
        cowork_id: str,
        participant: dict[str, Any],
        prompt_text: str,
        max_turn_sec: int,
        **kwargs: Any,
    ) -> TurnOutcome:
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

    try:
        participants = _build_participants()
        request = _request_from_participants(task, participants)
        request = request.model_copy(update={"scenario": {**request.scenario, "project_id": project_id, "objective": task}})
        started = await orchestrator.start_cowork(request=request, participants=participants)
        snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
        assert snapshot["status"] == "failed"
        assert snapshot["final_report"] is None
        planning_stage = next(row for row in snapshot["stages"] if str(row.get("stage_type")) == "planning")
        assert planning_stage["raw_outcome_status"] == "timeout"
        assert snapshot["last_timeout_event"]["stage_type"] == "planning"
        assert snapshot["last_timeout_event"]["role"] == "planner"
    finally:
        await orchestrator.shutdown()
        store.close()
