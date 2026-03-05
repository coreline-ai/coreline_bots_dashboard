from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from telegram_bot_new.mock_messenger.cowork import CoworkOrchestrator
from telegram_bot_new.mock_messenger.store import MockMessengerStore


async def _sender(_token: str, _chat_id: int, _user_id: int, _text: str) -> dict[str, Any]:
    return {"ok": True}


def _build_orchestrator(tmp_path: Path) -> tuple[CoworkOrchestrator, MockMessengerStore]:
    store = MockMessengerStore(
        db_path=str(tmp_path / "cowork-contract.db"),
        data_dir=str(tmp_path / "cowork-contract-data"),
    )
    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=_sender,
        poll_interval_sec=0.01,
        cool_down_sec=0.0,
    )
    return orchestrator, store


def test_cowork_stage_prompts_include_contract_sections(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        participants = [
            {"label": "Bot A", "bot_id": "bot-a", "role": "planner"},
            {"label": "Bot B", "bot_id": "bot-b", "role": "executor"},
            {"label": "Bot C", "bot_id": "bot-c", "role": "integrator"},
            {"label": "Bot D", "bot_id": "bot-d", "role": "controller"},
        ]
        planning = orchestrator._build_planning_prompt(
            task_text="꽃집 랜더링 페이지 구현",
            participants=participants,
            planner=participants[0],
        )
        execution = orchestrator._build_execution_prompt(
            task_text="꽃집 랜더링 페이지 구현",
            task_no=1,
            plan={"title": "UI 구현", "goal": "화면 구현", "done_criteria": "링크 제공", "risk": "누락"},
            assignee=participants[1],
        )
        integration = orchestrator._build_integration_prompt(
            task_text="꽃집 랜더링 페이지 구현",
            integrator=participants[2],
            execution_rows=[],
        )
        finalization = orchestrator._build_finalization_prompt(
            task_text="꽃집 랜더링 페이지 구현",
            controller=participants[3],
            integration_text="통합요약: 완료",
            execution_rows=[],
        )

        assert "[계약]" in planning and "[출력 규격]" in planning
        assert "[계약]" in execution and "증빙:" in execution and "[출력 형식]" in execution
        assert "[계약]" in integration and "QA승인:" in integration and "[출력 형식]" in integration
        assert "[계약]" in finalization and "증빙요약:" in finalization and "[출력 형식]" in finalization
    finally:
        store.close()


def test_owner_role_assignment_routes_to_matching_participant(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        participants = [
            {"label": "Bot A", "bot_id": "bot-a", "role": "controller"},
            {"label": "Bot B", "bot_id": "bot-b", "role": "planner"},
            {"label": "Bot C", "bot_id": "bot-c", "role": "implementer"},
            {"label": "Bot D", "bot_id": "bot-d", "role": "qa"},
        ]
        role_map = orchestrator._role_map(participants)
        role_cursors = {"implementer": 0, "planner": 0, "qa": 0, "controller": 0}
        qa = orchestrator._assignee_for_owner_role(owner_role="qa", role_map=role_map, role_cursors=role_cursors)
        controller = orchestrator._assignee_for_owner_role(
            owner_role="controller",
            role_map=role_map,
            role_cursors=role_cursors,
        )
        implementer = orchestrator._assignee_for_owner_role(
            owner_role="implementer",
            role_map=role_map,
            role_cursors=role_cursors,
        )
        assert qa["bot_id"] == "bot-d"
        assert controller["bot_id"] == "bot-a"
        assert implementer["bot_id"] == "bot-c"
    finally:
        store.close()


def test_compose_task_with_scenario_appends_allowed_fields(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        text = orchestrator._compose_task_with_scenario(
            base_task="기본 요청",
            scenario={
                "project_id": "p-1",
                "objective": "검증",
                "required_sections": ["hero", "cta"],
                "priority": "P0",
                "ignored": "x",
            },
        )
        assert "기본 요청" in text
        assert "project_id: p-1" in text
        assert "objective: 검증" in text
        assert "required_sections: hero, cta" in text
        assert "priority: P0" in text
        assert "ignored:" not in text
    finally:
        store.close()


def test_quality_gate_fails_on_connection_refused_trace(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        execution_rows = [
            {
                "status": "success",
                "response_text": "결과요약: 실행됨\n실행링크: http://127.0.0.1:9082/flower\n남은이슈: ERR_CONNECTION_REFUSED",
            }
        ]
        final_report = {
            "final_conclusion": "실행 가능",
            "execution_checklist": "브라우저 확인 완료",
            "execution_link": "http://127.0.0.1:9082/flower",
            "integrated_summary": "통합 완료",
            "evidence_summary": "ERR_CONNECTION_REFUSED 재현 로그 존재",
            "recommended_fixes": "서버 기동 확인",
        }

        gate = orchestrator._evaluate_completion_gate(
            task_text="꽃집 랜더링 페이지 만들어줘",
            execution_rows=execution_rows,
            final_report=final_report,
        )
        assert gate.passed is False
        assert any("ERR_CONNECTION_REFUSED" in failure for failure in gate.failures)
    finally:
        store.close()


def test_quality_gate_can_recover_execution_link_from_task_evidence(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        execution_rows = [
            {
                "status": "success",
                "response_text": "결과요약: 화면 구현 완료\n검증: 통과\n실행링크: http://127.0.0.1:9082/flower-shop\n남은이슈: 없음",
            }
        ]
        final_report = {
            "final_conclusion": "실행 가능",
            "execution_checklist": "기능/링크 점검",
            "execution_link": "없음",
            "integrated_summary": "통합 완료",
            "evidence_summary": "로그 확인",
            "recommended_fixes": "없음",
            "qa_signoff": "APPROVED",
        }

        gate = orchestrator._evaluate_completion_gate(
            task_text="꽃집 랜더링 페이지 만들어줘",
            execution_rows=execution_rows,
            final_report=final_report,
        )
        assert gate.passed is True
        assert gate.execution_link == "http://127.0.0.1:9082/flower-shop"
    finally:
        store.close()


def test_quality_gate_fails_when_open_high_defect_exists(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        gate = orchestrator._evaluate_completion_gate(
            task_text="랜딩 페이지 구현",
            execution_rows=[{"status": "success", "response_text": "결과요약: ok"}],
            final_report={
                "final_conclusion": "실행 가능",
                "execution_checklist": "검증 완료",
                "qa_signoff": "APPROVED",
                "defects": [
                    {
                        "defect_id": "D-001",
                        "severity": "high",
                        "status": "open",
                        "summary": "핵심 CTA 동작 불량",
                    }
                ],
            },
        )
        assert gate.passed is False
        assert any("Critical/High" in failure for failure in gate.failures)
    finally:
        store.close()


def test_quality_gate_fails_when_high_defect_exists_even_if_not_open(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        gate = orchestrator._evaluate_completion_gate(
            task_text="랜딩 페이지 구현",
            execution_rows=[{"status": "success", "response_text": "결과요약: ok"}],
            final_report={
                "final_conclusion": "실행 가능",
                "execution_checklist": "검증 완료",
                "qa_signoff": "APPROVED",
                "defects": [
                    {
                        "defect_id": "D-001",
                        "severity": "high",
                        "status": "verified",
                        "summary": "핵심 CTA 동작 불량",
                    }
                ],
            },
        )
        assert gate.passed is False
        assert any("Critical/High 결함" in failure for failure in gate.failures)
    finally:
        store.close()


def test_requires_render_link_does_not_false_positive_on_required_sections_keyword(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        task_text = (
            "테스트 작업\n"
            "required_sections: hero, product, trust, cta\n"
            "priority: P1"
        )
        assert orchestrator._requires_render_link(task_text) is False
    finally:
        store.close()


def test_workflow_documents_are_generated_from_snapshot(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        cowork_id = "c-policy-1"
        planning_response = "\n".join(
            [
                json.dumps(
                    {
                        "id": "T1",
                        "title": "요구 분석",
                        "goal": "요구 정리",
                        "done_criteria": "요구사항 목록 작성",
                        "risk": "누락",
                        "owner_role": "implementer",
                        "parallel_group": "G1",
                        "dependencies": [],
                        "artifacts": ["design_spec.md"],
                        "estimated_hours": 1.0,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "T2",
                        "title": "구현",
                        "goal": "기능 개발",
                        "done_criteria": "테스트 통과",
                        "risk": "회귀",
                        "owner_role": "implementer",
                        "parallel_group": "G2",
                        "dependencies": ["T1"],
                        "artifacts": ["qa_test_plan.md"],
                        "estimated_hours": 2.0,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        snapshot: dict[str, Any] = {
            "cowork_id": cowork_id,
            "task": "정책 문서 생성 테스트",
            "status": "completed",
            "stages": [
                {
                    "stage_type": "planning",
                    "response_text": planning_response,
                }
            ],
            "tasks": [
                {
                    "task_no": 1,
                    "title": "요구 분석",
                    "status": "success",
                    "assignee_label": "Bot C",
                    "response_text": "결과요약: 완료\n검증: 충족\n남은이슈: 없음",
                }
            ],
            "final_report": {
                "final_conclusion": "완료",
                "execution_checklist": "체크 완료",
                "quality_gate_failures": [],
            },
        }
        root = tmp_path / "workflow-artifacts"
        root.mkdir(parents=True, exist_ok=True)
        orchestrator._planning_review_cache[cowork_id] = [
            {"round": 1, "approved": True, "feedback": "ok", "source": "controller"}
        ]

        orchestrator._write_workflow_documents(cowork_id=cowork_id, snapshot=snapshot, root=root)

        assert (root / "planning" / "planning_tasks.json").is_file()
        assert (root / "planning" / "controller_kickoff.md").is_file()
        assert (root / "planning" / "PRD.md").is_file()
        assert (root / "planning" / "TRD.md").is_file()
        assert (root / "planning" / "DB.md").is_file()
        assert (root / "planning" / "test_strategy.md").is_file()
        assert (root / "planning" / "release_plan.md").is_file()
        assert (root / "planning" / "design_spec.md").is_file()
        assert (root / "planning" / "qa_test_plan.md").is_file()
        assert (root / "planning" / "controller_review_rounds.md").is_file()
        assert (root / "planning" / "controller_gate_review_round_1.md").is_file()
        assert (root / "implementation" / "implementation_report_round_1.md").is_file()
        assert (root / "implementation" / "test_execution_log_round_1.md").is_file()
        assert (root / "qa" / "qa_result_round_1.md").is_file()
        assert (root / "qa" / "defect_report_round_1.json").is_file()
        assert (root / "qa" / "qa_signoff.md").is_file()
        assert (root / "final" / "controller_final_report.md").is_file()
        assert (root / "final" / "workflow_trace.json").is_file()
        assert (root / "final" / "workflow_relational.md").is_file()

        planning_json = json.loads((root / "planning" / "planning_tasks.json").read_text(encoding="utf-8"))
        assert isinstance(planning_json.get("planning_tasks"), list)
        assert len(planning_json["planning_tasks"]) == 2
    finally:
        store.close()


def test_workflow_documents_write_planning_failed_on_planning_failure(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        cowork_id = "c-policy-fail"
        snapshot: dict[str, Any] = {
            "cowork_id": cowork_id,
            "task": "실패 케이스",
            "status": "failed",
            "error_summary": "planning schema/controller review failed",
            "stages": [
                {
                    "stage_type": "planning",
                    "status": "failed",
                    "error_text": "planning schema/controller review failed",
                    "response_text": "",
                }
            ],
            "tasks": [],
            "final_report": {},
        }
        root = tmp_path / "workflow-failed-artifacts"
        root.mkdir(parents=True, exist_ok=True)
        orchestrator._planning_review_cache[cowork_id] = [
            {"round": 1, "approved": False, "feedback": "schema 누락", "source": "schema"},
            {"round": 2, "approved": False, "feedback": "controller 반려", "source": "controller"},
            {"round": 3, "approved": False, "feedback": "최종 반려", "source": "controller"},
        ]
        orchestrator._write_workflow_documents(cowork_id=cowork_id, snapshot=snapshot, root=root)
        assert (root / "planning" / "planning_failed.md").is_file()
    finally:
        store.close()


def test_workflow_documents_generate_multi_round_artifacts(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        cowork_id = "c-policy-rounds"
        planning_response = "\n".join(
            [
                json.dumps(
                    {
                        "id": "T1",
                        "title": "구현 1",
                        "goal": "기본 구현",
                        "done_criteria": "완료",
                        "risk": "누락",
                        "owner_role": "implementer",
                        "parallel_group": "G1",
                        "dependencies": [],
                        "artifacts": ["design_spec.md"],
                        "estimated_hours": 1.0,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "T2",
                        "title": "구현 2",
                        "goal": "보강 구현",
                        "done_criteria": "완료",
                        "risk": "회귀",
                        "owner_role": "implementer",
                        "parallel_group": "G2",
                        "dependencies": ["T1"],
                        "artifacts": ["qa_test_plan.md"],
                        "estimated_hours": 1.0,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        snapshot: dict[str, Any] = {
            "cowork_id": cowork_id,
            "task": "라운드 산출물 테스트",
            "status": "completed",
            "stages": [
                {"stage_type": "planning", "response_text": planning_response},
                {
                    "stage_type": "qa",
                    "response_text": "QA결론: FAIL\n결함요약: 버튼 오류\n재현절차: 클릭\n수정요청: 수정\nQA승인: REJECTED",
                },
                {
                    "stage_type": "qa",
                    "response_text": "QA결론: PASS\n결함요약: 없음\n재현절차: 없음\n수정요청: 없음\nQA승인: APPROVED",
                },
            ],
            "tasks": [
                {
                    "task_no": 1,
                    "title": "구현 1",
                    "status": "success",
                    "assignee_label": "Bot C",
                    "spec_json": {"_round_no": 1},
                    "response_text": "결과요약: 완료\n검증: 충족\n남은이슈: 없음",
                },
                {
                    "task_no": 2,
                    "title": "구현 2",
                    "status": "success",
                    "assignee_label": "Bot D",
                    "spec_json": {"_round_no": 2},
                    "response_text": "결과요약: 완료\n검증: 충족\n남은이슈: 없음",
                },
            ],
            "final_report": {"quality_gate_failures": []},
        }
        root = tmp_path / "workflow-round-artifacts"
        root.mkdir(parents=True, exist_ok=True)
        orchestrator._write_workflow_documents(cowork_id=cowork_id, snapshot=snapshot, root=root)
        assert (root / "implementation" / "implementation_report_round_1.md").is_file()
        assert (root / "implementation" / "implementation_report_round_2.md").is_file()
        assert (root / "implementation" / "test_execution_log_round_1.md").is_file()
        assert (root / "implementation" / "test_execution_log_round_2.md").is_file()
        assert (root / "qa" / "qa_result_round_1.md").is_file()
        assert (root / "qa" / "qa_result_round_2.md").is_file()
        assert (root / "qa" / "defect_report_round_1.json").is_file()
        assert (root / "qa" / "defect_report_round_2.json").is_file()
    finally:
        store.close()


def test_artifact_dir_is_scoped_by_project_and_cowork(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        cowork_id = "c-scope-1"
        orchestrator._project_meta_cache[cowork_id] = {"project_id": "p-scope"}
        path = orchestrator._artifact_dir(cowork_id)
        assert path == (Path.cwd() / "result" / "p-scope" / cowork_id)
    finally:
        store.close()


def test_workflow_documents_use_planner_doc_content_when_provided(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        cowork_id = "c-policy-doc-content"
        planning_response = json.dumps(
            {
                "planning_tasks": [
                    {
                        "id": "T1",
                        "title": "요구 분석",
                        "goal": "요구 정리",
                        "done_criteria": "요구사항 목록 작성",
                        "risk": "누락",
                        "owner_role": "implementer",
                        "parallel_group": "G1",
                        "dependencies": [],
                        "artifacts": ["design_spec.md"],
                        "estimated_hours": 1.0,
                    },
                    {
                        "id": "T2",
                        "title": "구현",
                        "goal": "기능 개발",
                        "done_criteria": "테스트 통과",
                        "risk": "회귀",
                        "owner_role": "implementer",
                        "parallel_group": "G2",
                        "dependencies": ["T1"],
                        "artifacts": ["qa_test_plan.md"],
                        "estimated_hours": 2.0,
                    },
                ],
                "design_doc_path": "design_spec.md",
                "qa_plan_path": "qa_test_plan.md",
                "design_doc_content": "# Design Spec\n\n- custom: planner body",
                "qa_plan_content": "# QA Test Plan\n\n- custom: planner body",
            },
            ensure_ascii=False,
        )
        snapshot: dict[str, Any] = {
            "cowork_id": cowork_id,
            "task": "문서 본문 반영 테스트",
            "status": "completed",
            "stages": [{"stage_type": "planning", "response_text": planning_response}],
            "tasks": [],
            "final_report": {},
        }
        root = tmp_path / "workflow-doc-content-artifacts"
        root.mkdir(parents=True, exist_ok=True)
        orchestrator._write_workflow_documents(cowork_id=cowork_id, snapshot=snapshot, root=root)
        design_body = (root / "planning" / "design_spec.md").read_text(encoding="utf-8")
        qa_body = (root / "planning" / "qa_test_plan.md").read_text(encoding="utf-8")
        assert "custom: planner body" in design_body
        assert "custom: planner body" in qa_body
    finally:
        store.close()


def test_workflow_trace_step9_requires_qa_signoff(tmp_path: Path) -> None:
    orchestrator, store = _build_orchestrator(tmp_path)
    try:
        trace_missing = orchestrator._build_workflow_trace_rows(
            snapshot={
                "cowork_id": "c1",
                "status": "completed",
                "stages": [{"stage_type": "qa"}, {"stage_type": "controller_gate"}],
                "tasks": [],
                "final_report": {"qa_signoff": ""},
            }
        )
        step9_missing = next(row for row in trace_missing if int(row.get("step") or 0) == 9)
        assert str(step9_missing.get("status")) == "incomplete"

        trace_done = orchestrator._build_workflow_trace_rows(
            snapshot={
                "cowork_id": "c2",
                "status": "completed",
                "stages": [{"stage_type": "qa"}, {"stage_type": "controller_gate"}],
                "tasks": [],
                "final_report": {"qa_signoff": "APPROVED"},
            }
        )
        step9_done = next(row for row in trace_done if int(row.get("step") or 0) == 9)
        assert str(step9_done.get("status")) == "done"
    finally:
        store.close()
