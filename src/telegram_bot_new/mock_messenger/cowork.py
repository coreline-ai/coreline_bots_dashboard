from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from datetime import date, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from telegram_bot_new.mock_messenger.cowork_fallbacks import (
    WEB_PROJECT_PROFILES,
    audit_web_project,
    ensure_web_project_scaffold,
    resolve_web_project_profile,
    synthesize_finalization_from_audit,
    synthesize_qa_from_audit,
)
from telegram_bot_new.mock_messenger.schemas import SCENARIO_REQUIRED_KEYS, CoworkStartRequest, CoworkStatusResponse
from telegram_bot_new.mock_messenger.store import MockMessengerStore

EVENT_LINE_RE = re.compile(r"^\[(\d+|~)\]\[(\d{2}:\d{2}:\d{2})\]\[([a-z_]+)\]\s?(.*)$", re.IGNORECASE)
TURN_FAILED_RE = re.compile(r'"status"\s*:\s*"(error|failed|timeout)"|\bstatus\s*=\s*(error|failed|timeout)\b', re.IGNORECASE)
TURN_SUCCESS_RE = re.compile(r'"status"\s*:\s*"(ok|success|completed)"|\bstatus\s*=\s*(ok|success|completed)\b', re.IGNORECASE)
ERROR_HINTS = (
    "[error]",
    "[delivery_error]",
    "delivery_error",
    "executable not found",
    "send error",
    "failed to send telegram message",
)
ACTIVE_RUN_HINTS = (
    "a run is active",
    "run is already active",
    "already active in this chat",
    "use /stop first",
)
GEMINI_HUMAN_INPUT_HINTS = (
    "human input",
    "requires human input",
    "requires confirmation",
    "interactive confirmation",
    "approval required",
    "please confirm",
    "press enter",
    "open browser",
    "sign in",
    "login required",
    "oauth",
    "authenticate",
    "consent",
    "manual step",
    "사용자 확인",
    "휴먼 입력",
    "로그인 필요",
    "브라우저에서 인증",
    "인증 필요",
)
LINK_RE = re.compile(r"(https?://[^\s)]+|(?:localhost|127\.0\.0\.1):\d+[^\s)]*)", re.IGNORECASE)
ERR_CONNECTION_REFUSED_HINT = "err_connection_refused"
RENDER_TASK_HINTS = (
    "render",
    "renderer",
    "game",
    "games",
    "tetris",
    "playable",
    "ui",
    "web",
    "page",
    "screen",
    "layout",
    "게임",
    "테트리스",
    "플레이",
    "랜더",
    "렌더",
    "화면",
    "페이지",
    "웹",
)
FAILURE_VERDICT_HINTS = (
    "미이행",
    "미완료",
    "불가",
    "부재",
    "진척이 0",
    "0%",
)
CRITICAL_SEVERITY_HINTS = ("critical", "치명", "fatal", "blocker", "sev0", "sev-0")
HIGH_SEVERITY_HINTS = ("high", "높음", "major", "sev1", "sev-1", "p0")
CANONICAL_ROLES = ("controller", "planner", "implementer", "qa")
LEGACY_ROLE_ALIASES = {
    "executor": "implementer",
    "integrator": "qa",
}
ALLOWED_ROLES = tuple(CANONICAL_ROLES) + tuple(LEGACY_ROLE_ALIASES.keys())
PLANNING_OWNER_ROLES = ("controller", "planner", "implementer", "qa")
PLANNING_TASK_ID_RE = re.compile(r"^T[1-9]\d*$")
PLANNING_PARALLEL_GROUP_RE = re.compile(r"^G[1-9]\d*$")
STAGE_SCHEMA_MAX_RETRIES = 2
DEFAULT_MAX_AUTO_REPAIR_ROUNDS = 12
DEFAULT_MAX_NO_PROGRESS_ROUNDS = 5
DEFAULT_MAX_PLANNING_ATTEMPTS = 5
IMPLEMENTATION_REQUIRED_LABELS = ("결과요약", "검증", "남은이슈")
QA_REQUIRED_LABELS = ("QA결론", "결함요약", "재현절차", "수정요청", "QA승인")
FINALIZATION_REQUIRED_LABELS = ("최종결론", "실행체크리스트", "즉시실행항목(Top3)")
CONTROLLER_GATE_REQUIRED_LABELS = ("게이트결론", "게이트체크리스트", "다음조치(Top3)")


@dataclass(frozen=True)
class StagePolicy:
    timeout_floor_sec: int
    max_agent_attempts: int = 1
    allow_stop_retry: bool = False
    allow_provider_fallback: bool = True
    allow_deterministic_fallback: bool = False
    soft_gate_on_reject: bool = False


STAGE_POLICIES: dict[str, StagePolicy] = {
    "planning": StagePolicy(timeout_floor_sec=120, max_agent_attempts=2, allow_stop_retry=True, allow_deterministic_fallback=False),
    "planning_review": StagePolicy(timeout_floor_sec=60, max_agent_attempts=2, soft_gate_on_reject=True),
    "implementation": StagePolicy(timeout_floor_sec=180, max_agent_attempts=2, allow_stop_retry=True, allow_deterministic_fallback=True),
    "qa": StagePolicy(timeout_floor_sec=90, max_agent_attempts=2, allow_stop_retry=True, allow_deterministic_fallback=True),
    "finalization": StagePolicy(timeout_floor_sec=90, max_agent_attempts=2, allow_stop_retry=True, allow_deterministic_fallback=True),
    "controller_gate": StagePolicy(timeout_floor_sec=90, max_agent_attempts=2, allow_stop_retry=True, allow_deterministic_fallback=True),
}


CoworkSendFn = Callable[[str, int, int, str], Awaitable[dict[str, Any]]]


class ActiveCoworkExistsError(RuntimeError):
    pass


class CoworkNotFoundError(RuntimeError):
    pass


@dataclass
class TurnOutcome:
    done: bool
    status: str
    detail: str
    response_text: str | None = None
    error_text: str | None = None
    effective_timeout_sec: int | None = None


@dataclass
class QualityGateResult:
    passed: bool
    failures: list[str]
    requires_render_link: bool
    execution_link: str | None = None


@dataclass
class PlanningReviewResult:
    approved: bool
    feedback: str


@dataclass
class PlanningSubmission:
    tasks: list[dict[str, Any]]
    design_doc_path: str
    qa_plan_path: str
    prd_path: str = "PRD.md"
    trd_path: str = "TRD.md"
    db_path: str = "DB.md"
    test_strategy_path: str = "test_strategy.md"
    release_plan_path: str = "release_plan.md"
    prd_content: str | None = None
    trd_content: str | None = None
    db_content: str | None = None
    test_strategy_content: str | None = None
    release_plan_content: str | None = None
    design_doc_content: str | None = None
    qa_plan_content: str | None = None


class CoworkOrchestrator:
    def __init__(
        self,
        *,
        store: MockMessengerStore,
        send_user_message: CoworkSendFn,
        poll_interval_sec: float = 0.25,
        cool_down_sec: float = 0.2,
        artifact_root: str | Path | None = None,
        max_rework_rounds: int | None = None,
    ) -> None:
        self._store = store
        self._send_user_message = send_user_message
        self._poll_interval_sec = max(0.05, float(poll_interval_sec))
        self._cool_down_sec = max(0.0, float(cool_down_sec))
        root = Path(artifact_root) if artifact_root is not None else (Path.cwd() / "result")
        self._artifact_root = root.expanduser().resolve()
        configured_rework_rounds = (
            max_rework_rounds
            if max_rework_rounds is not None
            else int(os.getenv("COWORK_MAX_AUTO_REPAIR_ROUNDS") or DEFAULT_MAX_AUTO_REPAIR_ROUNDS)
        )
        self._max_rework_rounds = max(0, int(configured_rework_rounds))
        self._max_no_progress_rounds = max(
            1,
            int(os.getenv("COWORK_MAX_NO_PROGRESS_ROUNDS") or DEFAULT_MAX_NO_PROGRESS_ROUNDS),
        )
        self._max_planning_attempts = max(
            1,
            int(os.getenv("COWORK_MAX_PLANNING_ATTEMPTS") or DEFAULT_MAX_PLANNING_ATTEMPTS),
        )
        self._lock = asyncio.Lock()
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._planning_meta_cache: dict[str, dict[str, str]] = {}
        self._planning_review_cache: dict[str, list[dict[str, Any]]] = {}
        self._project_meta_cache: dict[str, dict[str, str]] = {}
        self._scenario_cache: dict[str, dict[str, Any]] = {}
        self._cowork_meta_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _normalize_role_name(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in LEGACY_ROLE_ALIASES:
            return LEGACY_ROLE_ALIASES[normalized]
        if normalized in CANONICAL_ROLES:
            return normalized
        return "implementer"

    def set_send_message_handler(self, handler: CoworkSendFn) -> None:
        self._send_user_message = handler

    async def start_cowork(
        self,
        *,
        request: CoworkStartRequest,
        participants: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self._lock:
            active = self._store.get_active_cowork()
            if active is not None:
                raise ActiveCoworkExistsError(active.get("cowork_id"))

            task_text = self._compose_task_with_scenario(
                base_task=request.task.strip(),
                scenario=request.scenario if isinstance(request.scenario, dict) else None,
            )
            normalized = self._normalize_roles(participants)
            cowork_id = self._store.create_cowork(
                task=task_text,
                max_parallel=int(request.max_parallel),
                max_turn_sec=int(request.max_turn_sec),
                fresh_session=bool(request.fresh_session),
                keep_partial_on_error=bool(request.keep_partial_on_error),
                participants=normalized,
            )
            scenario = self._extract_scenario_inputs(task_text)
            self._validate_scenario_contract(scenario=scenario)
            self._scenario_cache[cowork_id] = dict(scenario)
            project_profile = resolve_web_project_profile(task_text=task_text, scenario=scenario)
            self._project_meta_cache[cowork_id] = {
                "project_id": str(scenario.get("project_id") or cowork_id),
                "project_profile": str(project_profile or ""),
            }
            budget_floor_sec, budget_reason = self._estimate_cowork_budget(
                cowork_id=cowork_id,
                task_text=task_text,
                max_turn_sec=int(request.max_turn_sec),
                plan_items=None,
            )
            self._apply_budget_metadata(
                cowork_id=cowork_id,
                budget_floor_sec=budget_floor_sec,
                budget_applied_sec=budget_floor_sec,
                budget_auto_raised=False,
                budget_reason=budget_reason,
            )
            self._cowork_meta_cache[cowork_id] = {
                "project_profile": project_profile,
                "planning_gate_status": None,
                "agent_success": False,
                "artifact_agent_success": False,
                "fallback_used": False,
                "artifact_fallback_used": False,
                "controller_feedback": "",
                "auto_repair_round_limit": self._max_rework_rounds,
                "planning_attempt_limit": self._max_planning_attempts,
                "last_repair_signature": "",
                "no_progress_rounds": 0,
            }
            self._ensure_artifact_workspace(cowork_id)
            self._active_tasks[cowork_id] = asyncio.create_task(self._run_cowork(cowork_id), name=f"cowork:{cowork_id}")

        snapshot = self.get_cowork_snapshot(cowork_id)
        assert snapshot is not None
        return snapshot

    def _compose_task_with_scenario(self, *, base_task: str, scenario: dict[str, Any] | None) -> str:
        text = str(base_task or "").strip()
        if not scenario:
            return text
        allowed_keys = (
            "project_id",
            "objective",
            "brand_tone",
            "target_audience",
            "core_cta",
            "required_sections",
            "forbidden_elements",
            "constraints",
            "deadline",
            "priority",
        )
        lines: list[str] = [text]
        for key in allowed_keys:
            value = scenario.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                rendered = ", ".join(str(row).strip() for row in value if str(row).strip())
                if not rendered:
                    continue
                lines.append(f"{key}: {rendered}")
            else:
                rendered = str(value).strip()
                if not rendered:
                    continue
                lines.append(f"{key}: {rendered}")
        return "\n".join(row for row in lines if row.strip())

    def _validate_scenario_contract(self, *, scenario: dict[str, Any]) -> None:
        missing: list[str] = []
        for key in SCENARIO_REQUIRED_KEYS:
            value = scenario.get(key)
            if isinstance(value, list):
                if not [str(row).strip() for row in value if str(row).strip()]:
                    missing.append(key)
            elif not str(value or "").strip():
                missing.append(key)
        if missing:
            raise ValueError(f"scenario contract missing required fields: {', '.join(missing)}")

    def _scenario_for_cowork(self, *, cowork_id: str, task_text: str) -> dict[str, Any]:
        cached = self._scenario_cache.get(cowork_id)
        if isinstance(cached, dict) and cached:
            return dict(cached)
        scenario = self._extract_scenario_inputs(task_text)
        self._scenario_cache[cowork_id] = dict(scenario)
        return scenario

    def _cowork_meta(self, cowork_id: str) -> dict[str, Any]:
        return self._cowork_meta_cache.setdefault(
            cowork_id,
            {
                "project_profile": None,
                "planning_gate_status": None,
                "agent_success": False,
                "artifact_agent_success": False,
                "fallback_used": False,
                "artifact_fallback_used": False,
                "controller_feedback": "",
                "auto_repair_round_limit": self._max_rework_rounds,
                "planning_attempt_limit": self._max_planning_attempts,
                "last_repair_signature": "",
                "no_progress_rounds": 0,
            },
        )

    def _build_prompt_proposal(
        self,
        *,
        cowork_id: str,
        task_text: str,
        stage: str,
        round_no: int,
        failures: list[str] | None = None,
        final_report: dict[str, Any] | None = None,
        execution_rows: list[dict[str, Any]] | None = None,
    ) -> str:
        scenario = self._scenario_for_cowork(cowork_id=cowork_id, task_text=task_text)
        artifact_dir = self._artifact_dir(cowork_id)
        failure_lines = [str(row).strip() for row in (failures or []) if str(row).strip()]
        actions: list[str] = []
        if stage == "planning":
            actions = [
                "요구를 1~5개 작업으로 최소 분해하고 각 작업의 owner_role/dependencies/artifacts를 명시",
                "PRD/TRD/DB/Test/Release/Design/QA 문서 본문을 모두 채워 JSON 객체 하나로 제출",
                "Implementer가 즉시 index.html, styles.css, README.md를 생성할 수 있도록 완료조건을 구체적으로 고정",
                "기획 문구는 placeholder가 아니라 실제 사용자용 카피로 작성",
            ]
        else:
            actions = [
                "마지막 실패 원인을 산출물 파일 또는 검증 결과 기준으로 직접 수정",
                "index.html, styles.css, README.md를 실제로 갱신하고 placeholder 문구를 제거",
                "수정 후 테스트를 다시 수행하고 증빙/실행링크/남은이슈를 갱신",
                "이전 응답을 반복하지 말고 실패 항목이 사라졌음을 결과로 증명",
            ]
        if isinstance(final_report, dict):
            qa_signoff = str(final_report.get("qa_signoff") or "").strip()
            if qa_signoff:
                actions.append(f"QA 상태를 {qa_signoff}에서 APPROVED 또는 PASS로 끌어올릴 것")
        if execution_rows:
            failed_rows = [
                f"T{int(row.get('task_no') or 0)}:{str(row.get('title') or '')}:{str(row.get('status') or '')}"
                for row in execution_rows
                if str(row.get("status") or "") != "success"
            ]
            if failed_rows:
                actions.append(f"실패 태스크 우선 복구: {', '.join(failed_rows[:3])}")
        lines = [
            "[Self-Healing Prompt Proposal]",
            f"- stage: {stage}",
            f"- round: {round_no}",
            f"- project_id: {scenario.get('project_id')}",
            f"- objective: {scenario.get('objective')}",
            f"- brand_tone: {scenario.get('brand_tone')}",
            f"- target_audience: {scenario.get('target_audience')}",
            f"- core_cta: {scenario.get('core_cta')}",
            f"- required_sections: {', '.join(str(item).strip() for item in scenario.get('required_sections') or []) or '없음'}",
            f"- artifact_dir: {artifact_dir}",
            "- success_definition: 실제 산출물 생성 + 테스트/증빙 확보 + QA/Final gate 통과",
            "- required_files: index.html, styles.css, README.md",
            "- artifact_quality_bar: placeholder 금지, 실제 카피/레이아웃/CTA/검증 근거 포함",
            "- process_safety: 장기 실행 프로세스를 foreground로 띄우지 말 것. 서버/감시 프로세스는 백그라운드로 시작 후 검증 직후 종료할 것",
        ]
        if failure_lines:
            lines.append("- current_failures:")
            lines.extend(f"  - {row}" for row in failure_lines[:8])
        else:
            lines.append("- current_failures: 없음")
        lines.append("- next_actions:")
        lines.extend(f"  {index}. {action}" for index, action in enumerate(actions, start=1))
        return "\n".join(lines).strip()

    def _write_prompt_proposal_artifact(
        self,
        *,
        cowork_id: str,
        stage: str,
        round_no: int,
        proposal_text: str,
    ) -> None:
        root = self._ensure_artifact_workspace(cowork_id)
        if stage == "planning":
            parent = root / "planning"
            filename = f"prompt_proposal_round_{round_no}.md"
        else:
            parent = root / "implementation"
            filename = f"prompt_proposal_rework_round_{round_no}.md"
        parent.mkdir(parents=True, exist_ok=True)
        (parent / filename).write_text(proposal_text.strip() + "\n", encoding="utf-8")

    def _compute_repair_signature(
        self,
        *,
        cowork_id: str,
        failures: list[str],
        final_report: dict[str, Any],
    ) -> str:
        artifact_rows: list[dict[str, Any]] = []
        root = self._artifact_dir(cowork_id)
        if root.exists():
            for path in sorted(row for row in root.rglob("*") if row.is_file()):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                artifact_rows.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "size": int(stat.st_size),
                        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                    }
                )
        payload = {
            "failures": list(failures[:8]),
            "qa_signoff": str(final_report.get("qa_signoff") or ""),
            "completion_status": str(final_report.get("completion_status") or ""),
            "artifacts": artifact_rows[:200],
        }
        return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _project_profile_for_cowork(self, *, cowork_id: str, task_text: str) -> str | None:
        meta = self._cowork_meta(cowork_id)
        cached = str(meta.get("project_profile") or "").strip()
        if cached:
            return cached
        project_meta = self._project_meta_cache.get(cowork_id, {})
        project_cached = str(project_meta.get("project_profile") or "").strip()
        if project_cached:
            meta["project_profile"] = project_cached
            return project_cached
        scenario = self._scenario_for_cowork(cowork_id=cowork_id, task_text=task_text)
        resolved = resolve_web_project_profile(task_text=task_text, scenario=scenario)
        meta["project_profile"] = resolved
        self._project_meta_cache.setdefault(cowork_id, {})["project_profile"] = str(resolved or "")
        return resolved

    def _stage_policy(self, stage_type: str) -> StagePolicy:
        return STAGE_POLICIES.get(str(stage_type or "").strip().lower(), StagePolicy(timeout_floor_sec=45))

    @staticmethod
    def _env_flag(name: str, default: bool = False) -> bool:
        raw = str(os.getenv(name) or "").strip().lower()
        if not raw:
            return default
        return raw in {"1", "true", "yes", "on"}

    def _is_web_project_profile(self, *, cowork_id: str, task_text: str) -> bool:
        profile = self._project_profile_for_cowork(cowork_id=cowork_id, task_text=task_text)
        return bool(profile and profile in WEB_PROJECT_PROFILES)

    def _is_web_artifact_authoritative_mode(self, *, cowork_id: str, task_text: str) -> bool:
        return self._is_web_project_profile(cowork_id=cowork_id, task_text=task_text)

    def _allow_web_deterministic_fallback(self) -> bool:
        return self._env_flag("COWORK_WEB_ALLOW_DETERMINISTIC_FALLBACK", default=False)

    def _is_web_guaranteed_mode(self, *, cowork_id: str, task_text: str) -> bool:
        return self._is_web_artifact_authoritative_mode(cowork_id=cowork_id, task_text=task_text) and self._allow_web_deterministic_fallback()

    def _allow_web_planner_augment(self) -> bool:
        return self._env_flag("COWORK_WEB_ALLOW_PLANNER_AUGMENT", default=False)

    def _requires_real_web_artifact(self, *, cowork_id: str, task_text: str) -> bool:
        return self._is_web_project_profile(cowork_id=cowork_id, task_text=task_text) and not self._allow_web_deterministic_fallback()

    def _estimate_cowork_budget(
        self,
        *,
        cowork_id: str,
        task_text: str,
        max_turn_sec: int,
        plan_items: list[dict[str, Any]] | None = None,
    ) -> tuple[int, str]:
        if self._is_web_guaranteed_mode(cowork_id=cowork_id, task_text=task_text):
            planning = max(int(max_turn_sec), self._stage_policy("planning").timeout_floor_sec)
            return (planning + 30, "web_guaranteed_mode: planner + deterministic artifact audit path")
        planning = max(int(max_turn_sec), self._stage_policy("planning").timeout_floor_sec)
        planning_review = self._stage_policy("planning_review").timeout_floor_sec
        implementation = max(int(max_turn_sec), self._stage_policy("implementation").timeout_floor_sec)
        qa = self._stage_policy("qa").timeout_floor_sec
        finalization = self._stage_policy("finalization").timeout_floor_sec
        task_count = len(plan_items or [])
        if task_count <= 0:
            task_count = 1
        floor = planning + planning_review + (implementation * task_count) + qa + finalization
        return (floor, f"stage_floor_sum: planning+review+implementation*{task_count}+qa+finalization")

    def _apply_budget_metadata(
        self,
        *,
        cowork_id: str,
        budget_floor_sec: int,
        budget_applied_sec: int | None = None,
        budget_auto_raised: bool = False,
        budget_reason: str | None = None,
    ) -> None:
        self._store.set_cowork_budget(
            cowork_id=cowork_id,
            budget_floor_sec=budget_floor_sec,
            budget_applied_sec=budget_applied_sec if budget_applied_sec is not None else budget_floor_sec,
            budget_auto_raised=budget_auto_raised,
            budget_reason=budget_reason,
        )

    def _record_timeout_event(
        self,
        *,
        cowork_id: str,
        origin: str,
        participant: dict[str, Any] | None = None,
        stage_type: str | None = None,
        task_no: int | None = None,
        effective_timeout_sec: int | None = None,
        detail: str | None = None,
    ) -> None:
        payload = {
            "origin": str(origin or "").strip() or "turn_timeout",
            "bot_id": str((participant or {}).get("bot_id") or ""),
            "label": str((participant or {}).get("label") or (participant or {}).get("bot_id") or ""),
            "role": self._normalize_role_name((participant or {}).get("role") or "implementer"),
            "stage_type": str(stage_type or "").strip() or None,
            "task_no": int(task_no) if task_no is not None else None,
            "effective_timeout_sec": int(effective_timeout_sec) if effective_timeout_sec is not None else None,
            "detail": str(detail or "").strip() or None,
        }
        self._store.set_cowork_timeout_event(cowork_id=cowork_id, event=payload)

    def _finish_stage_record(
        self,
        *,
        stage_id: int,
        resolved_status: str,
        response_text: str | None = None,
        error_text: str | None = None,
        outcome: TurnOutcome | None = None,
        fallback_applied: bool = False,
        fallback_source: str | None = None,
    ) -> None:
        self._store.finish_cowork_stage(
            stage_id=stage_id,
            status=resolved_status,
            response_text=response_text,
            error_text=error_text,
            resolved_status=resolved_status,
            raw_outcome_status=str(outcome.status) if outcome is not None else None,
            raw_outcome_detail=str(outcome.detail) if outcome is not None else None,
            raw_outcome_error_text=str(outcome.error_text) if outcome is not None and outcome.error_text is not None else None,
            fallback_applied=fallback_applied,
            fallback_source=fallback_source,
            effective_timeout_sec=int(outcome.effective_timeout_sec) if outcome is not None and outcome.effective_timeout_sec is not None else None,
        )

    def _finish_task_record(
        self,
        *,
        task_id: int,
        resolved_status: str,
        response_text: str | None = None,
        error_text: str | None = None,
        outcome: TurnOutcome | None = None,
        fallback_applied: bool = False,
        fallback_source: str | None = None,
        blocked_by_task_no: int | None = None,
        blocked_by_bot_id: str | None = None,
        blocked_by_reason: str | None = None,
    ) -> None:
        self._store.finish_cowork_task(
            task_id=task_id,
            status=resolved_status,
            response_text=response_text,
            error_text=error_text,
            resolved_status=resolved_status,
            raw_outcome_status=str(outcome.status) if outcome is not None else None,
            raw_outcome_detail=str(outcome.detail) if outcome is not None else None,
            raw_outcome_error_text=str(outcome.error_text) if outcome is not None and outcome.error_text is not None else None,
            fallback_applied=fallback_applied,
            fallback_source=fallback_source,
            effective_timeout_sec=int(outcome.effective_timeout_sec) if outcome is not None and outcome.effective_timeout_sec is not None else None,
            blocked_by_task_no=blocked_by_task_no,
            blocked_by_bot_id=blocked_by_bot_id,
            blocked_by_reason=blocked_by_reason,
        )

    def _mark_agent_success(self, *, cowork_id: str) -> None:
        self._cowork_meta(cowork_id)["agent_success"] = True

    def _mark_artifact_agent_success(self, *, cowork_id: str) -> None:
        self._cowork_meta(cowork_id)["artifact_agent_success"] = True

    def _mark_fallback_used(self, *, cowork_id: str) -> None:
        self._cowork_meta(cowork_id)["fallback_used"] = True

    def _mark_artifact_fallback_used(self, *, cowork_id: str) -> None:
        self._cowork_meta(cowork_id)["artifact_fallback_used"] = True

    def _scaffold_source_for_cowork(self, *, cowork_id: str) -> str | None:
        meta = self._cowork_meta(cowork_id)
        agent_success = bool(meta.get("artifact_agent_success"))
        fallback_used = bool(meta.get("artifact_fallback_used"))
        if agent_success and fallback_used:
            return "hybrid"
        if fallback_used:
            return "fallback"
        if agent_success:
            return "agent"
        return None

    def _artifact_relative_url(self, *, cowork_id: str, relative_path: str) -> str:
        clean_path = str(relative_path or "").lstrip("./")
        return f"/_mock/cowork/{cowork_id}/artifact/{clean_path}"

    def _ensure_project_scaffold_if_needed(self, *, cowork_id: str, task_text: str) -> dict[str, Any] | None:
        if not self._allow_web_deterministic_fallback():
            return None
        profile = self._project_profile_for_cowork(cowork_id=cowork_id, task_text=task_text)
        if not profile:
            return None
        scenario = self._scenario_for_cowork(cowork_id=cowork_id, task_text=task_text)
        result = ensure_web_project_scaffold(profile=profile, artifact_dir=self._artifact_dir(cowork_id), scenario=scenario)
        self._mark_fallback_used(cowork_id=cowork_id)
        self._mark_artifact_fallback_used(cowork_id=cowork_id)
        return result

    def _artifact_audit(self, *, cowork_id: str, task_text: str) -> dict[str, Any] | None:
        profile = self._project_profile_for_cowork(cowork_id=cowork_id, task_text=task_text)
        if not profile:
            return None
        return audit_web_project(
            profile=profile,
            artifact_dir=self._artifact_dir(cowork_id),
            strict_artifact=self._requires_real_web_artifact(cowork_id=cowork_id, task_text=task_text),
        )

    def _plan_artifact_paths(self, *, cowork_id: str, plan: dict[str, Any]) -> list[Path]:
        artifact_names = plan.get("artifacts") if isinstance(plan.get("artifacts"), list) else []
        root = self._artifact_dir(cowork_id)
        paths: list[Path] = []
        for name in artifact_names:
            relative = str(name or "").strip().lstrip("./")
            if not relative:
                continue
            paths.append((root / relative).resolve())
        return paths

    def _plan_artifacts_materialized(self, *, cowork_id: str, plan: dict[str, Any]) -> tuple[bool, list[str]]:
        missing: list[str] = []
        for path in self._plan_artifact_paths(cowork_id=cowork_id, plan=plan):
            if not path.is_file() or int(path.stat().st_size) <= 0:
                missing.append(path.name)
        return (len(missing) == 0, missing)

    @staticmethod
    def _materialized_plan_response(*, plan: dict[str, Any], reason: str) -> str:
        artifact_names = plan.get("artifacts") if isinstance(plan.get("artifacts"), list) else []
        rendered_artifacts = ", ".join(str(name).strip() for name in artifact_names if str(name).strip()) or "없음"
        return (
            "결과요약: 실제 산출물 파일이 결과 경로에 materialize됨\n"
            f"검증: {rendered_artifacts}\n"
            f"남은이슈: transport 상태 점검 필요 ({reason})"
        )

    def get_cowork_snapshot(self, cowork_id: str) -> dict[str, Any] | None:
        cowork = self._store.get_cowork(cowork_id=cowork_id)
        if cowork is None:
            return None
        stages = self._store.list_cowork_stages(cowork_id=cowork_id)
        tasks = self._store.list_cowork_tasks(cowork_id=cowork_id)
        participants = self._store.list_cowork_participants(cowork_id=cowork_id)
        current_stage_row = next((stage for stage in reversed(stages) if stage.get("status") == "running"), None)

        errors: list[dict[str, Any]] = []
        for stage in stages:
            status = str(stage.get("status") or "")
            if status in {"error", "timeout", "failed", "stopped"}:
                errors.append(
                    {
                        "source": "stage",
                        "source_id": int(stage["id"]),
                        "stage_type": str(stage.get("stage_type") or ""),
                        "task_no": None,
                        "bot_id": str(stage.get("actor_bot_id") or ""),
                        "label": str(stage.get("actor_label") or ""),
                        "role": self._normalize_role_name(stage.get("actor_role") or "implementer"),
                        "status": status,
                        "error_text": str(stage.get("error_text") or stage.get("response_text") or status),
                    }
                )
        for task in tasks:
            status = str(task.get("status") or "")
            if status in {"error", "timeout", "failed", "stopped"}:
                errors.append(
                    {
                        "source": "task",
                        "source_id": int(task["id"]),
                        "stage_type": None,
                        "task_no": int(task.get("task_no") or 0),
                        "bot_id": str(task.get("assignee_bot_id") or ""),
                        "label": str(task.get("assignee_label") or ""),
                        "role": self._normalize_role_name(task.get("assignee_role") or "implementer"),
                        "status": status,
                        "error_text": str(task.get("error_text") or task.get("response_text") or status),
                    }
                )

        payload: dict[str, Any] = {
            **cowork,
            "current_stage": str(current_stage_row.get("stage_type") or "") if current_stage_row else None,
            "current_actor": (
                {
                    "bot_id": str(current_stage_row.get("actor_bot_id") or ""),
                    "label": str(current_stage_row.get("actor_label") or ""),
                    "role": self._normalize_role_name(current_stage_row.get("actor_role") or "implementer"),
                }
                if current_stage_row
                else None
            ),
            "stages": stages,
            "tasks": tasks,
            "errors": errors,
            "participants": participants,
            "final_report": cowork.get("final_report"),
            "artifacts": self._build_artifact_payload(cowork_id),
        }
        return CoworkStatusResponse.model_validate(payload).model_dump()

    def get_active_cowork_snapshot(self) -> dict[str, Any] | None:
        active = self._store.get_active_cowork()
        if active is None:
            return None
        cowork_id = str(active.get("cowork_id") or "")
        if not cowork_id:
            return None
        return self.get_cowork_snapshot(cowork_id)

    async def stop_cowork(
        self,
        cowork_id: str,
        *,
        reason: str | None = None,
        source: str | None = None,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self.get_cowork_snapshot(cowork_id)
        if snapshot is None:
            raise CoworkNotFoundError(cowork_id)
        self._store.set_cowork_stop_requested(
            cowork_id=cowork_id,
            reason=reason,
            source=source,
            requested_by=requested_by,
        )
        if str(reason or "").strip().lower() == "case_timeout":
            self._record_timeout_event(
                cowork_id=cowork_id,
                origin="runner_case_timeout",
                participant={"label": source or "cowork-web-live-suite", "role": "controller"},
                stage_type=str(snapshot.get("current_stage") or ""),
                effective_timeout_sec=int(snapshot.get("budget_applied_sec") or snapshot.get("max_turn_sec") or 0) or None,
                detail=str(reason or "case timeout"),
            )
        updated = self.get_cowork_snapshot(cowork_id)
        assert updated is not None
        return updated

    def get_cowork_artifacts(self, cowork_id: str) -> dict[str, Any] | None:
        if self._store.get_cowork(cowork_id=cowork_id) is None:
            return None
        return self._build_artifact_payload(cowork_id)

    def resolve_artifact_path(self, cowork_id: str, filename: str) -> Path | None:
        requested = str(filename or "").strip()
        if not requested:
            return None
        if requested.startswith("/") or requested.startswith("\\"):
            return None
        relative = Path(requested)
        if any(part == ".." for part in relative.parts):
            return None
        root = self._artifact_read_dir(cowork_id).resolve()
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return path

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = list(self._active_tasks.values())
            self._active_tasks.clear()
        for task in tasks:
            if task.done():
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_cowork(self, cowork_id: str) -> None:
        try:
            cowork = self._store.get_cowork(cowork_id=cowork_id)
            if cowork is None:
                return
            participants = self._store.list_cowork_participants(cowork_id=cowork_id)
            if len(participants) < 2:
                self._store.finish_cowork(cowork_id=cowork_id, status="failed", error_summary="participants must be >= 2")
                return
            self._store.set_cowork_running(cowork_id=cowork_id)
            artifact_dir = self._ensure_artifact_workspace(cowork_id)

            if cowork.get("fresh_session"):
                await self._broadcast_control_command(participants, "/new")
            await self._broadcast_control_command(participants, "/stop")
            if self._cool_down_sec > 0:
                await asyncio.sleep(self._cool_down_sec)
            await self._broadcast_project_command(participants, artifact_dir)
            if self._cool_down_sec > 0:
                await asyncio.sleep(self._cool_down_sec)

            if self._is_stop_requested(cowork_id):
                self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
                return

            role_map = self._role_map(participants)
            max_turn_sec = int(cowork.get("max_turn_sec") or 60)
            keep_partial = bool(cowork.get("keep_partial_on_error"))
            root_task = str(cowork.get("task") or "")
            self._record_intake_stage(cowork_id=cowork_id, task_text=root_task, controller=role_map["controller"])

            plan_items = await self._stage_planning(
                cowork_id=cowork_id,
                task_text=root_task,
                planner=role_map["planner"],
                controller=role_map["controller"],
                participants=participants,
                max_turn_sec=max_turn_sec,
                keep_partial=keep_partial,
            )
            if plan_items is None:
                return
            budget_floor_sec, budget_reason = self._estimate_cowork_budget(
                cowork_id=cowork_id,
                task_text=root_task,
                max_turn_sec=max_turn_sec,
                plan_items=plan_items,
            )
            self._apply_budget_metadata(
                cowork_id=cowork_id,
                budget_floor_sec=budget_floor_sec,
                budget_applied_sec=budget_floor_sec,
                budget_auto_raised=False,
                budget_reason=budget_reason,
            )

            execution_rows = await self._stage_execution(
                cowork_id=cowork_id,
                task_text=root_task,
                plan_items=plan_items,
                role_map=role_map,
                max_parallel=int(cowork.get("max_parallel") or 3),
                max_turn_sec=max_turn_sec,
                task_no_start=1,
                round_no=1,
            )
            if execution_rows is None:
                return

            rework_round = 0
            while True:
                qa_text = await self._stage_integration(
                    cowork_id=cowork_id,
                    task_text=root_task,
                    integrator=role_map["qa"],
                    execution_rows=execution_rows,
                    max_turn_sec=max_turn_sec,
                )
                if qa_text is None:
                    return

                final_report = await self._stage_finalization(
                    cowork_id=cowork_id,
                    task_text=root_task,
                    controller=role_map["controller"],
                    integration_text=qa_text,
                    execution_rows=execution_rows,
                    max_turn_sec=max_turn_sec,
                )
                if final_report is None:
                    return

                self._apply_project_metadata_to_final_report(
                    cowork_id=cowork_id,
                    task_text=root_task,
                    final_report=final_report,
                )
                gate = self._evaluate_completion_gate(
                    cowork_id=cowork_id,
                    task_text=root_task,
                    execution_rows=execution_rows,
                    final_report=final_report,
                )
                final_report["completion_status"] = "passed" if gate.passed else "needs_rework"
                final_report["quality_gate_failures"] = gate.failures
                if gate.execution_link:
                    final_report["execution_link"] = gate.execution_link

                if gate.passed:
                    self._store.finish_cowork(cowork_id=cowork_id, status="completed", final_report=final_report)
                    return

                repair_signature = self._compute_repair_signature(
                    cowork_id=cowork_id,
                    failures=gate.failures,
                    final_report=final_report,
                )
                meta = self._cowork_meta(cowork_id)
                if str(meta.get("last_repair_signature") or "") == repair_signature:
                    meta["no_progress_rounds"] = int(meta.get("no_progress_rounds") or 0) + 1
                else:
                    meta["no_progress_rounds"] = 0
                meta["last_repair_signature"] = repair_signature
                if int(meta.get("no_progress_rounds") or 0) >= self._max_no_progress_rounds:
                    error_summary = "; ".join(gate.failures[:3]) or "quality gate failed"
                    self._store.finish_cowork(
                        cowork_id=cowork_id,
                        status="failed",
                        error_summary=f"self-healing stalled: {error_summary}",
                        final_report=final_report,
                    )
                    return

                if rework_round >= self._max_rework_rounds:
                    error_summary = "; ".join(gate.failures[:3]) or "quality gate failed"
                    self._store.finish_cowork(
                        cowork_id=cowork_id,
                        status="failed",
                        error_summary=f"quality gate failed: {error_summary}",
                        final_report=final_report,
                    )
                    return

                rework_round += 1
                self._record_rework_stage(
                    cowork_id=cowork_id,
                    controller=role_map["controller"],
                    round_no=rework_round,
                    failures=gate.failures,
                )
                defects = self._extract_defects(final_report)
                if defects:
                    rework_plan_items = self._build_defect_rework_plan_items(defects=defects, round_no=rework_round)
                else:
                    rework_plan_items = self._build_rework_plan_items(
                        task_text=root_task,
                        failures=gate.failures,
                        round_no=rework_round,
                    )
                proposal_text = self._build_prompt_proposal(
                    cowork_id=cowork_id,
                    task_text=root_task,
                    stage="rework",
                    round_no=rework_round,
                    failures=gate.failures,
                    final_report=final_report,
                    execution_rows=execution_rows,
                )
                self._write_prompt_proposal_artifact(
                    cowork_id=cowork_id,
                    stage="rework",
                    round_no=rework_round,
                    proposal_text=proposal_text,
                )
                rework_task_text = self._build_rework_task_text(
                    task_text=root_task,
                    failures=gate.failures,
                    round_no=rework_round,
                    proposal_text=proposal_text,
                )
                execution_rows = await self._stage_execution(
                    cowork_id=cowork_id,
                    task_text=rework_task_text,
                    plan_items=rework_plan_items,
                    role_map=role_map,
                    max_parallel=int(cowork.get("max_parallel") or 3),
                    max_turn_sec=max_turn_sec,
                    task_no_start=len(execution_rows) + 1,
                    round_no=rework_round + 1,
                )
                if execution_rows is None:
                    return
        except asyncio.CancelledError:
            cowork = self._store.get_cowork(cowork_id=cowork_id)
            if cowork is not None and cowork.get("status") in {"queued", "running"}:
                self._store.finish_cowork(cowork_id=cowork_id, status="stopped", error_summary="cowork task cancelled")
            raise
        except Exception as error:  # pragma: no cover
            self._store.finish_cowork(cowork_id=cowork_id, status="failed", error_summary=str(error))
        finally:
            self._write_cowork_artifacts(cowork_id)
            async with self._lock:
                self._active_tasks.pop(cowork_id, None)
                self._planning_meta_cache.pop(cowork_id, None)
                self._planning_review_cache.pop(cowork_id, None)
                self._project_meta_cache.pop(cowork_id, None)
                self._scenario_cache.pop(cowork_id, None)
                self._cowork_meta_cache.pop(cowork_id, None)

    async def _stage_planning(
        self,
        *,
        cowork_id: str,
        task_text: str,
        planner: dict[str, Any],
        controller: dict[str, Any],
        participants: list[dict[str, Any]],
        max_turn_sec: int,
        keep_partial: bool,
    ) -> list[dict[str, Any]] | None:
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None
        artifact_dir = self._artifact_dir(cowork_id)
        scenario = self._scenario_for_cowork(cowork_id=cowork_id, task_text=task_text)
        planning_policy = self._stage_policy("planning")
        review_policy = self._stage_policy("planning_review")
        project_profile = self._project_profile_for_cowork(cowork_id=cowork_id, task_text=task_text)
        budget_floor_sec, budget_reason = self._estimate_cowork_budget(
            cowork_id=cowork_id,
            task_text=task_text,
            max_turn_sec=max_turn_sec,
            plan_items=None,
        )
        self._apply_budget_metadata(
            cowork_id=cowork_id,
            budget_floor_sec=budget_floor_sec,
            budget_applied_sec=budget_floor_sec,
            budget_auto_raised=False,
            budget_reason=budget_reason,
        )
        self._planning_review_cache[cowork_id] = []
        planning_response_text: str | None = None
        planning_gate_status = "failed"
        failure_reason = ""
        submission: PlanningSubmission | None = None
        final_outcome = TurnOutcome(done=True, status="failed", detail="planning_not_started", error_text="planning not started")
        final_stage_id = 0
        feedback_reasons: list[str] = []

        for round_no in range(1, self._max_planning_attempts + 1):
            proposal_text = self._build_prompt_proposal(
                cowork_id=cowork_id,
                task_text=task_text,
                stage="planning",
                round_no=round_no,
                failures=feedback_reasons,
            )
            self._write_prompt_proposal_artifact(
                cowork_id=cowork_id,
                stage="planning",
                round_no=round_no,
                proposal_text=proposal_text,
            )
            prompt_text = (
                self._build_planning_prompt(
                    task_text=task_text,
                    participants=participants,
                    planner=planner,
                    scenario=scenario,
                    artifact_dir=artifact_dir,
                    proposal_text=proposal_text,
                )
                if round_no == 1
                else self._build_planning_rejection_prompt(
                    task_text=task_text,
                    participants=participants,
                    planner=planner,
                    scenario=scenario,
                    feedback_reasons=feedback_reasons,
                    round_no=round_no,
                    artifact_dir=artifact_dir,
                    proposal_text=proposal_text,
                )
            )
            stage_id = self._store.insert_cowork_stage_start(
                cowork_id=cowork_id,
                stage_no=self._next_stage_no(cowork_id),
                stage_type="planning",
                actor_bot_id=str(planner.get("bot_id") or ""),
                actor_label=str(planner.get("label") or ""),
                actor_role=str(planner.get("role") or "planner"),
                prompt_text=prompt_text,
            )
            outcome = await self._run_turn_with_recovery(
                cowork_id=cowork_id,
                participant=planner,
                prompt_text=prompt_text,
                max_turn_sec=max_turn_sec,
                timeout_floor_sec=planning_policy.timeout_floor_sec,
                max_agent_attempts=planning_policy.max_agent_attempts,
                allow_stop_retry=planning_policy.allow_stop_retry,
                allow_provider_fallback=planning_policy.allow_provider_fallback,
            )
            final_outcome = outcome
            final_stage_id = stage_id
            planning_response_text = outcome.response_text

            if outcome.status != "success":
                failure_reason = outcome.error_text or outcome.detail or "planning failed"
                feedback_reasons = [failure_reason]
                self._planning_review_cache[cowork_id].append(
                    {
                        "round": round_no,
                        "approved": False,
                        "feedback": failure_reason,
                        "source": "planner_runtime",
                    }
                )
                if outcome.status == "timeout" or self._looks_like_stream_timeout_outcome(outcome):
                    self._record_timeout_event(
                        cowork_id=cowork_id,
                        origin="turn_timeout",
                        participant=planner,
                        stage_type="planning",
                        effective_timeout_sec=outcome.effective_timeout_sec,
                        detail=outcome.error_text or outcome.detail,
                    )
                self._finish_stage_record(
                    stage_id=stage_id,
                    resolved_status="failed",
                    response_text=planning_response_text,
                    error_text=failure_reason,
                    outcome=outcome,
                )
                if round_no < self._max_planning_attempts:
                    continue
                break

            parsed_submission, planning_errors = self._parse_planning_submission(outcome.response_text or "")
            planning_errors.extend(
                self._validate_planning_submission(
                    parsed_submission,
                    require_doc_contents=bool(project_profile and project_profile in WEB_PROJECT_PROFILES),
                )
            )
            if planning_errors:
                failure_reason = "; ".join(planning_errors[:5])
                feedback_reasons = list(planning_errors[:8])
                self._planning_review_cache[cowork_id].append(
                    {
                        "round": round_no,
                        "approved": False,
                        "feedback": failure_reason,
                        "source": "schema",
                    }
                )
                self._finish_stage_record(
                    stage_id=stage_id,
                    resolved_status="failed",
                    response_text=planning_response_text,
                    error_text=failure_reason,
                    outcome=outcome,
                )
                if round_no < self._max_planning_attempts:
                    continue
                break

            submission = parsed_submission
            budget_floor_sec, budget_reason = self._estimate_cowork_budget(
                cowork_id=cowork_id,
                task_text=task_text,
                max_turn_sec=max_turn_sec,
                plan_items=submission.tasks,
            )
            self._apply_budget_metadata(
                cowork_id=cowork_id,
                budget_floor_sec=budget_floor_sec,
                budget_applied_sec=budget_floor_sec,
                budget_auto_raised=False,
                budget_reason=budget_reason,
            )
            review = await self._review_planning_plan(
                cowork_id=cowork_id,
                task_text=task_text,
                planner=planner,
                controller=controller,
                plan_items=submission.tasks,
                max_turn_sec=max(max_turn_sec, review_policy.timeout_floor_sec),
                round_no=round_no,
            )
            self._planning_review_cache[cowork_id].append(
                {
                    "round": round_no,
                    "approved": review.approved,
                    "feedback": review.feedback,
                    "source": "controller",
                }
            )
            self._cowork_meta(cowork_id)["controller_feedback"] = review.feedback
            if review.approved:
                planning_gate_status = "approved"
                self._mark_agent_success(cowork_id=cowork_id)
                self._finish_stage_record(
                    stage_id=stage_id,
                    resolved_status="success",
                    response_text=planning_response_text,
                    error_text=None,
                    outcome=outcome,
                )
                break
            if review_policy.soft_gate_on_reject:
                planning_gate_status = "soft_pass"
                self._finish_stage_record(
                    stage_id=stage_id,
                    resolved_status="success",
                    response_text=planning_response_text,
                    error_text=None,
                    outcome=outcome,
                )
                break
            failure_reason = review.feedback or "planning review rejected"
            feedback_reasons = [failure_reason]
            submission = None
            self._finish_stage_record(
                stage_id=stage_id,
                resolved_status="failed",
                response_text=planning_response_text,
                error_text=failure_reason,
                outcome=outcome,
            )
            if round_no < self._max_planning_attempts:
                continue
            break

        if submission is None or planning_gate_status not in {"approved", "soft_pass"}:
            self._cowork_meta(cowork_id)["planning_gate_status"] = "failed"
            self._store.finish_cowork(
                cowork_id=cowork_id,
                status="failed",
                error_summary=failure_reason or final_outcome.error_text or final_outcome.detail or "planning failed",
            )
            return None

        self._cowork_meta(cowork_id)["planning_gate_status"] = planning_gate_status

        docs_context = [
            submission.prd_content,
            submission.trd_content,
            submission.db_content,
            submission.test_strategy_content,
            submission.release_plan_content,
            submission.design_doc_content,
            submission.qa_plan_content,
        ]
        planning_context = "\n\n".join(str(row).strip() for row in docs_context if str(row or "").strip())
        self._planning_meta_cache[cowork_id] = {
            "design_doc_path": submission.design_doc_path,
            "qa_plan_path": submission.qa_plan_path,
            "prd_path": submission.prd_path,
            "trd_path": submission.trd_path,
            "db_path": submission.db_path,
            "test_strategy_path": submission.test_strategy_path,
            "release_plan_path": submission.release_plan_path,
            "design_doc_content": submission.design_doc_content or "",
            "qa_plan_content": submission.qa_plan_content or "",
            "prd_content": submission.prd_content or "",
            "trd_content": submission.trd_content or "",
            "db_content": submission.db_content or "",
            "test_strategy_content": submission.test_strategy_content or "",
            "release_plan_content": submission.release_plan_content or "",
            "design_doc_excerpt": (submission.design_doc_content or "")[:800],
            "qa_plan_excerpt": (submission.qa_plan_content or "")[:800],
            "planning_context_excerpt": planning_context[:1200],
            "controller_feedback": str(self._cowork_meta(cowork_id).get("controller_feedback") or failure_reason or ""),
        }

        if project_profile:
            self._ensure_project_scaffold_if_needed(cowork_id=cowork_id, task_text=task_text)
        return submission.tasks

    async def _stage_execution(
        self,
        *,
        cowork_id: str,
        task_text: str,
        plan_items: list[dict[str, Any]],
        role_map: dict[str, Any],
        max_parallel: int,
        max_turn_sec: int,
        task_no_start: int = 1,
        round_no: int = 1,
    ) -> list[dict[str, Any]] | None:
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None
        artifact_dir = self._artifact_dir(cowork_id)
        self._ensure_project_scaffold_if_needed(cowork_id=cowork_id, task_text=task_text)
        planning_meta = self._planning_meta_cache.get(cowork_id, {})
        design_doc_path = Path(str(planning_meta.get("design_doc_path") or "design_spec.md")).name
        qa_plan_path = Path(str(planning_meta.get("qa_plan_path") or "qa_test_plan.md")).name
        design_doc_excerpt = str(planning_meta.get("design_doc_excerpt") or "").strip()
        qa_plan_excerpt = str(planning_meta.get("qa_plan_excerpt") or "").strip()
        planning_context_excerpt = str(planning_meta.get("planning_context_excerpt") or "").strip()
        web_guaranteed = self._is_web_guaranteed_mode(cowork_id=cowork_id, task_text=task_text)

        execution_rows: list[dict[str, Any]] = []
        role_cursors = {"implementer": 0, "planner": 0, "qa": 0, "controller": 0}
        stage_no_base = self._next_stage_no(cowork_id)
        for index, item in enumerate(plan_items, start=1):
            task_no = int(task_no_start) + index - 1
            owner_role = self._normalize_role_name(item.get("owner_role") or "implementer")
            assignee = self._assignee_for_owner_role(
                owner_role=owner_role,
                role_map=role_map,
                role_cursors=role_cursors,
            )
            stage_no = stage_no_base + index - 1
            spec_payload = dict(item)
            spec_payload["_round_no"] = int(round_no)
            task_id = self._store.insert_cowork_task(
                cowork_id=cowork_id,
                task_no=task_no,
                title=str(item.get("title") or f"Task {task_no}"),
                spec_json=spec_payload,
                assignee_bot_id=str(assignee.get("bot_id") or ""),
                assignee_label=str(assignee.get("label") or ""),
                assignee_role=str(assignee.get("role") or "implementer"),
                status="pending",
            )
            execution_rows.append(
                {
                    "task_id": task_id,
                    "task_no": task_no,
                    "task_key": str(item.get("id") or f"T{task_no}"),
                    "stage_no": stage_no,
                    "plan": item,
                    "owner_role": owner_role,
                    "assignee": assignee,
                }
            )

        semaphore = asyncio.Semaphore(max(1, int(max_parallel)))
        participant_semaphores: dict[tuple[str, str], asyncio.Semaphore] = {}

        def _participant_semaphore(participant: dict[str, Any]) -> asyncio.Semaphore:
            key = self._participant_scope_key(participant)
            existing = participant_semaphores.get(key)
            if existing is not None:
                return existing
            created = asyncio.Semaphore(1)
            participant_semaphores[key] = created
            return created

        async def _run_one(row: dict[str, Any]) -> bool:
            assignee = row["assignee"]
            async with semaphore:
                async with _participant_semaphore(assignee):
                    if self._is_stop_requested(cowork_id):
                        stopped_outcome = TurnOutcome(done=True, status="stopped", detail="stop_requested", error_text="stop requested")
                        self._finish_task_record(
                            task_id=int(row["task_id"]),
                            resolved_status="stopped",
                            error_text="stop requested",
                            outcome=stopped_outcome,
                        )
                        return False

                    plan = row["plan"]
                    owner_role = self._normalize_role_name(row.get("owner_role") or plan.get("owner_role") or "implementer")
                    stage_type = self._stage_type_for_owner_role(owner_role)
                    required_labels = self._required_labels_for_stage(stage_type)
                    self._store.start_cowork_task(task_id=int(row["task_id"]))
                    prompt_text = self._build_role_task_prompt(
                        task_text=task_text,
                        task_no=int(row["task_no"]),
                        plan=plan,
                        assignee=assignee,
                        owner_role=owner_role,
                        artifact_dir=artifact_dir,
                        design_doc_path=design_doc_path,
                        qa_plan_path=qa_plan_path,
                        design_doc_excerpt=design_doc_excerpt,
                        qa_plan_excerpt=qa_plan_excerpt,
                        planning_context_excerpt=planning_context_excerpt,
                    )
                    stage_id = self._store.insert_cowork_stage_start(
                        cowork_id=cowork_id,
                        stage_no=int(row.get("stage_no") or self._next_stage_no(cowork_id)),
                        stage_type=stage_type,
                        actor_bot_id=str(assignee.get("bot_id") or ""),
                        actor_label=str(assignee.get("label") or ""),
                        actor_role=str(assignee.get("role") or "implementer"),
                        prompt_text=prompt_text,
                    )

                    if web_guaranteed:
                        audit = self._artifact_audit(cowork_id=cowork_id, task_text=task_text)
                        if audit and audit.get("passed"):
                            auto_response = self._fallback_task_response(
                                cowork_id=cowork_id,
                                task_text=task_text,
                                stage_type=stage_type,
                                plan=plan,
                            )
                            auto_outcome = TurnOutcome(done=True, status="skipped", detail="web_guaranteed_execution_bypass")
                            self._mark_fallback_used(cowork_id=cowork_id)
                            self._finish_task_record(
                                task_id=int(row["task_id"]),
                                resolved_status="success",
                                response_text=auto_response,
                                outcome=auto_outcome,
                                fallback_applied=True,
                                fallback_source="deterministic_scaffold",
                            )
                            self._finish_stage_record(
                                stage_id=stage_id,
                                resolved_status="success",
                                response_text=auto_response,
                                outcome=auto_outcome,
                                fallback_applied=True,
                                fallback_source="deterministic_scaffold",
                            )
                            return True

                    if stage_type == "implementation" and self._requires_real_web_artifact(cowork_id=cowork_id, task_text=task_text):
                        materialized_before_run, _missing_before_run = self._plan_artifacts_materialized(cowork_id=cowork_id, plan=plan)
                        if materialized_before_run:
                            auto_outcome = TurnOutcome(done=True, status="skipped", detail="artifact_already_materialized")
                            auto_response = self._materialized_plan_response(plan=plan, reason="artifacts already present before turn")
                            self._mark_agent_success(cowork_id=cowork_id)
                            self._mark_artifact_agent_success(cowork_id=cowork_id)
                            self._finish_task_record(
                                task_id=int(row["task_id"]),
                                resolved_status="success",
                                response_text=auto_response,
                                outcome=auto_outcome,
                            )
                            self._finish_stage_record(
                                stage_id=stage_id,
                                resolved_status="success",
                                response_text=auto_response,
                                outcome=auto_outcome,
                            )
                            return True

                    try:
                        stage_policy = self._stage_policy(stage_type)
                        outcome = await self._run_turn_with_recovery(
                            cowork_id=cowork_id,
                            participant=assignee,
                            prompt_text=prompt_text,
                            max_turn_sec=max_turn_sec,
                            timeout_floor_sec=stage_policy.timeout_floor_sec,
                            max_agent_attempts=stage_policy.max_agent_attempts,
                            allow_stop_retry=stage_policy.allow_stop_retry,
                            allow_provider_fallback=stage_policy.allow_provider_fallback,
                        )
                    except Exception as error:
                        outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text=str(error))
                    outcome = await self._enforce_stage_schema(
                        cowork_id=cowork_id,
                        participant=assignee,
                        stage_type=stage_type,
                        required_labels=required_labels,
                        max_turn_sec=max_turn_sec,
                        outcome=outcome,
                    )

                    if outcome.status == "success":
                        if stage_type == "implementation" and self._requires_real_web_artifact(cowork_id=cowork_id, task_text=task_text):
                            audit = self._artifact_audit(cowork_id=cowork_id, task_text=task_text)
                            if not audit or not audit.get("passed"):
                                failure_reason = "; ".join(list((audit or {}).get("artifact_audit_failures") or [])[:3]) or "artifact contract unmet"
                                error_text = (
                                    "실제 산출물 파일이 생성되지 않았습니다. "
                                    f"필수 artifact를 경로에 직접 작성해야 합니다: {failure_reason}"
                                )
                                self._finish_task_record(
                                    task_id=int(row["task_id"]),
                                    resolved_status="failed",
                                    response_text=outcome.response_text,
                                    error_text=error_text,
                                    outcome=outcome,
                                )
                                self._finish_stage_record(
                                    stage_id=stage_id,
                                    resolved_status="failed",
                                    response_text=outcome.response_text,
                                    error_text=error_text,
                                    outcome=outcome,
                                )
                                return False
                            self._mark_artifact_agent_success(cowork_id=cowork_id)
                        self._mark_agent_success(cowork_id=cowork_id)
                        self._finish_task_record(
                            task_id=int(row["task_id"]),
                            resolved_status="success",
                            response_text=outcome.response_text,
                            outcome=outcome,
                        )
                        self._finish_stage_record(
                            stage_id=stage_id,
                            resolved_status="success",
                            response_text=outcome.response_text,
                            outcome=outcome,
                        )
                        return True

                    if outcome.status == "timeout" or self._looks_like_stream_timeout_outcome(outcome):
                        self._record_timeout_event(
                            cowork_id=cowork_id,
                            origin="turn_timeout",
                            participant=assignee,
                            stage_type=stage_type,
                            task_no=int(row["task_no"]),
                            effective_timeout_sec=outcome.effective_timeout_sec,
                            detail=outcome.error_text or outcome.detail,
                        )

                    if stage_type == "implementation" and self._requires_real_web_artifact(cowork_id=cowork_id, task_text=task_text):
                        materialized_after_error, _missing_after_error = self._plan_artifacts_materialized(cowork_id=cowork_id, plan=plan)
                        if materialized_after_error:
                            recovered_response = self._materialized_plan_response(
                                plan=plan,
                                reason=outcome.error_text or outcome.detail or "turn failure after file creation",
                            )
                            self._mark_agent_success(cowork_id=cowork_id)
                            self._mark_artifact_agent_success(cowork_id=cowork_id)
                            self._finish_task_record(
                                task_id=int(row["task_id"]),
                                resolved_status="success",
                                response_text=recovered_response,
                                outcome=outcome,
                            )
                            self._finish_stage_record(
                                stage_id=stage_id,
                                resolved_status="success",
                                response_text=recovered_response,
                                outcome=outcome,
                            )
                            return True

                    fallback_response = None
                    if stage_policy.allow_deterministic_fallback:
                        fallback_response = self._fallback_task_response(
                            cowork_id=cowork_id,
                            task_text=task_text,
                            stage_type=stage_type,
                            plan=plan,
                        )
                    if fallback_response:
                        self._mark_fallback_used(cowork_id=cowork_id)
                        self._finish_task_record(
                            task_id=int(row["task_id"]),
                            resolved_status="success",
                            response_text=fallback_response,
                            outcome=outcome,
                            fallback_applied=True,
                            fallback_source="fallback_scaffold",
                        )
                        self._finish_stage_record(
                            stage_id=stage_id,
                            resolved_status="success",
                            response_text=fallback_response,
                            error_text=None,
                            outcome=outcome,
                            fallback_applied=True,
                            fallback_source="fallback_scaffold",
                        )
                        return True

                    self._finish_task_record(
                        task_id=int(row["task_id"]),
                        resolved_status=outcome.status,
                        response_text=outcome.response_text,
                        error_text=outcome.error_text or outcome.detail,
                        outcome=outcome,
                    )
                    self._finish_stage_record(
                        stage_id=stage_id,
                        resolved_status=outcome.status,
                        response_text=outcome.response_text,
                        error_text=outcome.error_text or outcome.detail,
                        outcome=outcome,
                    )
                    return False

        def _deps_satisfied(row: dict[str, Any], *, success_keys: set[str]) -> bool:
            deps = row.get("plan", {}).get("dependencies")
            if not isinstance(deps, list):
                return True
            return all(str(dep).strip() in success_keys for dep in deps)

        def _deps_include_failed(row: dict[str, Any], *, failed_keys: set[str]) -> bool:
            deps = row.get("plan", {}).get("dependencies")
            if not isinstance(deps, list):
                return False
            return any(str(dep).strip() in failed_keys for dep in deps)

        def _mark_dependency_failed(
            row: dict[str, Any],
            *,
            reason: str,
            blocked_by_task_no: int | None = None,
            blocked_by_bot_id: str | None = None,
        ) -> None:
            owner_role = self._normalize_role_name(row.get("owner_role") or row.get("plan", {}).get("owner_role") or "implementer")
            stage_type = self._stage_type_for_owner_role(owner_role)
            stage_id = self._store.insert_cowork_stage_start(
                cowork_id=cowork_id,
                stage_no=int(row.get("stage_no") or self._next_stage_no(cowork_id)),
                stage_type=stage_type,
                actor_bot_id=str(row.get("assignee", {}).get("bot_id") or ""),
                actor_label=str(row.get("assignee", {}).get("label") or ""),
                actor_role=str(row.get("assignee", {}).get("role") or owner_role),
                prompt_text=f"[자동실패] dependency gate: {reason}",
            )
            blocked_outcome = TurnOutcome(done=True, status="failed", detail=reason, error_text=reason)
            self._finish_task_record(
                task_id=int(row["task_id"]),
                resolved_status="failed",
                error_text=reason,
                outcome=blocked_outcome,
                blocked_by_task_no=blocked_by_task_no,
                blocked_by_bot_id=blocked_by_bot_id,
                blocked_by_reason=reason,
            )
            self._finish_stage_record(
                stage_id=stage_id,
                resolved_status="failed",
                error_text=reason,
                outcome=blocked_outcome,
            )

        def _parallel_group_rank(row: dict[str, Any]) -> int:
            value = str(row.get("plan", {}).get("parallel_group") or "G999").strip().upper()
            match = PLANNING_PARALLEL_GROUP_RE.match(value)
            if not match:
                return 999
            try:
                return int(value[1:])
            except Exception:
                return 999

        pending: dict[int, dict[str, Any]] = {int(row["task_id"]): row for row in execution_rows}
        success_keys: set[str] = set()
        failed_keys: set[str] = set()
        failed_rows_by_key: dict[str, dict[str, Any]] = {}

        while pending:
            blocked_ids = [
                task_id
                for task_id, row in pending.items()
                if _deps_include_failed(row, failed_keys=failed_keys)
            ]
            for task_id in blocked_ids:
                row = pending.pop(task_id)
                deps = row.get("plan", {}).get("dependencies")
                upstream = None
                if isinstance(deps, list):
                    upstream = next((failed_rows_by_key.get(str(dep).strip()) for dep in deps if str(dep).strip() in failed_rows_by_key), None)
                _mark_dependency_failed(
                    row,
                    reason="dependency_failed",
                    blocked_by_task_no=int(upstream.get("task_no")) if isinstance(upstream, dict) and upstream.get("task_no") is not None else None,
                    blocked_by_bot_id=str(upstream.get("assignee", {}).get("bot_id") or "") if isinstance(upstream, dict) else None,
                )
                task_key = str(row.get("task_key") or "")
                if task_key:
                    failed_keys.add(task_key)
                    failed_rows_by_key[task_key] = row

            ready_candidates = [
                row
                for row in pending.values()
                if _deps_satisfied(row, success_keys=success_keys)
            ]
            if not ready_candidates:
                for task_id, row in list(pending.items()):
                    pending.pop(task_id, None)
                    _mark_dependency_failed(row, reason="dependency_deadlock_or_unmet")
                    task_key = str(row.get("task_key") or "")
                    if task_key:
                        failed_keys.add(task_key)
                        failed_rows_by_key[task_key] = row
                break
            min_group_rank = min(_parallel_group_rank(row) for row in ready_candidates)
            ready_rows = [row for row in ready_candidates if _parallel_group_rank(row) == min_group_rank]

            results = await asyncio.gather(*[_run_one(row) for row in ready_rows])
            for row, ok in zip(ready_rows, results):
                pending.pop(int(row["task_id"]), None)
                task_key = str(row.get("task_key") or "")
                if not task_key:
                    continue
                if ok:
                    success_keys.add(task_key)
                else:
                    failed_keys.add(task_key)
                    failed_rows_by_key[task_key] = row

        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None
        return self._store.list_cowork_tasks(cowork_id=cowork_id)

    async def _stage_integration(
        self,
        *,
        cowork_id: str,
        task_text: str,
        integrator: dict[str, Any],
        execution_rows: list[dict[str, Any]],
        max_turn_sec: int,
    ) -> str | None:
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None

        if self._is_web_artifact_authoritative_mode(cowork_id=cowork_id, task_text=task_text):
            stage_id = self._store.insert_cowork_stage_start(
                cowork_id=cowork_id,
                stage_no=self._next_stage_no(cowork_id),
                stage_type="qa",
                actor_bot_id=str(integrator.get("bot_id") or ""),
                actor_label=str(integrator.get("label") or ""),
                actor_role=str(integrator.get("role") or "qa"),
                prompt_text="[web-guaranteed] artifact audit synthesized QA",
            )
            audit = self._artifact_audit(cowork_id=cowork_id, task_text=task_text)
            if audit:
                fallback_text = synthesize_qa_from_audit(audit)
                outcome = TurnOutcome(done=True, status="skipped", detail="web_guaranteed_qa_bypass")
                self._mark_fallback_used(cowork_id=cowork_id)
                self._finish_stage_record(
                    stage_id=stage_id,
                    resolved_status="success",
                    response_text=fallback_text,
                    outcome=outcome,
                    fallback_applied=True,
                    fallback_source="artifact_audit",
                )
                return fallback_text

        artifact_dir = self._artifact_dir(cowork_id)
        prompt_text = self._build_integration_prompt(
            task_text=task_text,
            integrator=integrator,
            execution_rows=execution_rows,
            artifact_dir=artifact_dir,
        )
        stage_id = self._store.insert_cowork_stage_start(
            cowork_id=cowork_id,
            stage_no=self._next_stage_no(cowork_id),
            stage_type="qa",
            actor_bot_id=str(integrator.get("bot_id") or ""),
            actor_label=str(integrator.get("label") or ""),
            actor_role=str(integrator.get("role") or "qa"),
            prompt_text=prompt_text,
        )
        try:
            stage_policy = self._stage_policy("qa")
            outcome = await self._run_turn_with_recovery(
                cowork_id=cowork_id,
                participant=integrator,
                prompt_text=prompt_text,
                max_turn_sec=max_turn_sec,
                timeout_floor_sec=stage_policy.timeout_floor_sec,
                max_agent_attempts=stage_policy.max_agent_attempts,
                allow_stop_retry=stage_policy.allow_stop_retry,
                allow_provider_fallback=stage_policy.allow_provider_fallback,
            )
        except Exception as error:
            outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text=str(error))
        outcome = await self._enforce_stage_schema(
            cowork_id=cowork_id,
            participant=integrator,
            stage_type="qa",
            required_labels=QA_REQUIRED_LABELS,
            max_turn_sec=max_turn_sec,
            outcome=outcome,
        )

        if outcome.status == "success":
            self._mark_agent_success(cowork_id=cowork_id)
            self._finish_stage_record(
                stage_id=stage_id,
                resolved_status="success",
                response_text=outcome.response_text,
                outcome=outcome,
            )
            return str(outcome.response_text or "")

        if outcome.status == "timeout" or self._looks_like_stream_timeout_outcome(outcome):
            self._record_timeout_event(
                cowork_id=cowork_id,
                origin="turn_timeout",
                participant=integrator,
                stage_type="qa",
                effective_timeout_sec=outcome.effective_timeout_sec,
                detail=outcome.error_text or outcome.detail,
            )

        fallback_text = None
        if stage_policy.allow_deterministic_fallback:
            audit = self._artifact_audit(cowork_id=cowork_id, task_text=task_text)
            if audit:
                fallback_text = synthesize_qa_from_audit(audit)
        if fallback_text:
            self._mark_fallback_used(cowork_id=cowork_id)
            self._finish_stage_record(
                stage_id=stage_id,
                resolved_status="success",
                response_text=fallback_text,
                outcome=outcome,
                fallback_applied=True,
                fallback_source="artifact_audit",
            )
            return fallback_text

        self._finish_stage_record(
            stage_id=stage_id,
            resolved_status=outcome.status,
            response_text=outcome.response_text,
            error_text=outcome.error_text or outcome.detail,
            outcome=outcome,
        )
        self._store.finish_cowork(
            cowork_id=cowork_id,
            status="failed",
            error_summary=outcome.error_text or outcome.detail or "qa stage failed",
        )
        return None

    async def _stage_finalization(
        self,
        *,
        cowork_id: str,
        task_text: str,
        controller: dict[str, Any],
        integration_text: str,
        execution_rows: list[dict[str, Any]],
        max_turn_sec: int,
    ) -> dict[str, Any] | None:
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None

        if self._is_web_artifact_authoritative_mode(cowork_id=cowork_id, task_text=task_text):
            stage_id = self._store.insert_cowork_stage_start(
                cowork_id=cowork_id,
                stage_no=self._next_stage_no(cowork_id),
                stage_type="finalization",
                actor_bot_id=str(controller.get("bot_id") or ""),
                actor_label=str(controller.get("label") or ""),
                actor_role=str(controller.get("role") or "controller"),
                prompt_text="[web-guaranteed] artifact audit synthesized finalization",
            )
            audit = self._artifact_audit(cowork_id=cowork_id, task_text=task_text)
            if audit:
                fallback_payload = synthesize_finalization_from_audit(
                    audit,
                    self._scenario_for_cowork(cowork_id=cowork_id, task_text=task_text),
                )
                final_text = str(fallback_payload.get("text") or "")
                outcome = TurnOutcome(done=True, status="skipped", detail="web_guaranteed_finalization_bypass")
                self._mark_fallback_used(cowork_id=cowork_id)
                self._finish_stage_record(
                    stage_id=stage_id,
                    resolved_status="success",
                    response_text=final_text,
                    outcome=outcome,
                    fallback_applied=True,
                    fallback_source="artifact_audit",
                )
                final_report = self._build_final_report(
                    integration_text=integration_text,
                    finalization_text=final_text,
                    execution_rows=execution_rows,
                )
                final_report.update(
                    {
                        "final_conclusion": str(fallback_payload.get("final_conclusion") or final_report.get("final_conclusion") or ""),
                        "execution_checklist": str(fallback_payload.get("execution_checklist") or final_report.get("execution_checklist") or ""),
                        "entry_artifact_path": str(fallback_payload.get("entry_artifact_path") or ""),
                        "evidence_summary": str(fallback_payload.get("evidence_summary") or final_report.get("evidence_summary") or ""),
                        "immediate_actions_top3": list(fallback_payload.get("immediate_actions_top3") or final_report.get("immediate_actions_top3") or []),
                        "artifact_audit_failures": list(fallback_payload.get("artifact_audit_failures") or []),
                    }
                )
                self._apply_project_metadata_to_final_report(cowork_id=cowork_id, task_text=task_text, final_report=final_report)
                return final_report

        artifact_dir = self._artifact_dir(cowork_id)
        prompt_text = self._build_finalization_prompt(
            task_text=task_text,
            controller=controller,
            integration_text=integration_text,
            execution_rows=execution_rows,
            artifact_dir=artifact_dir,
        )
        stage_id = self._store.insert_cowork_stage_start(
            cowork_id=cowork_id,
            stage_no=self._next_stage_no(cowork_id),
            stage_type="finalization",
            actor_bot_id=str(controller.get("bot_id") or ""),
            actor_label=str(controller.get("label") or ""),
            actor_role=str(controller.get("role") or "controller"),
            prompt_text=prompt_text,
        )
        try:
            stage_policy = self._stage_policy("finalization")
            outcome = await self._run_turn_with_recovery(
                cowork_id=cowork_id,
                participant=controller,
                prompt_text=prompt_text,
                max_turn_sec=max_turn_sec,
                timeout_floor_sec=stage_policy.timeout_floor_sec,
                max_agent_attempts=stage_policy.max_agent_attempts,
                allow_stop_retry=stage_policy.allow_stop_retry,
                allow_provider_fallback=stage_policy.allow_provider_fallback,
            )
        except Exception as error:
            outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text=str(error))
        outcome = await self._enforce_stage_schema(
            cowork_id=cowork_id,
            participant=controller,
            stage_type="finalization",
            required_labels=FINALIZATION_REQUIRED_LABELS,
            max_turn_sec=max_turn_sec,
            outcome=outcome,
        )

        if outcome.status == "success":
            self._mark_agent_success(cowork_id=cowork_id)
            self._finish_stage_record(
                stage_id=stage_id,
                resolved_status="success",
                response_text=outcome.response_text,
                outcome=outcome,
            )
            final_report = self._build_final_report(
                integration_text=integration_text,
                finalization_text=str(outcome.response_text or ""),
                execution_rows=execution_rows,
            )
            self._apply_project_metadata_to_final_report(cowork_id=cowork_id, task_text=task_text, final_report=final_report)
            return final_report

        if outcome.status == "timeout" or self._looks_like_stream_timeout_outcome(outcome):
            self._record_timeout_event(
                cowork_id=cowork_id,
                origin="turn_timeout",
                participant=controller,
                stage_type="finalization",
                effective_timeout_sec=outcome.effective_timeout_sec,
                detail=outcome.error_text or outcome.detail,
            )

        fallback_payload = None
        if stage_policy.allow_deterministic_fallback:
            audit = self._artifact_audit(cowork_id=cowork_id, task_text=task_text)
            if audit:
                fallback_payload = synthesize_finalization_from_audit(audit, self._scenario_for_cowork(cowork_id=cowork_id, task_text=task_text))
        if fallback_payload:
            self._mark_fallback_used(cowork_id=cowork_id)
            final_text = str(fallback_payload.get("text") or "")
            self._finish_stage_record(
                stage_id=stage_id,
                resolved_status="success",
                response_text=final_text,
                outcome=outcome,
                fallback_applied=True,
                fallback_source="artifact_audit",
            )
            final_report = self._build_final_report(
                integration_text=integration_text,
                finalization_text=final_text,
                execution_rows=execution_rows,
            )
            final_report.update(
                {
                    "final_conclusion": str(fallback_payload.get("final_conclusion") or final_report.get("final_conclusion") or ""),
                    "execution_checklist": str(fallback_payload.get("execution_checklist") or final_report.get("execution_checklist") or ""),
                    "entry_artifact_path": str(fallback_payload.get("entry_artifact_path") or ""),
                    "evidence_summary": str(fallback_payload.get("evidence_summary") or final_report.get("evidence_summary") or ""),
                    "immediate_actions_top3": list(fallback_payload.get("immediate_actions_top3") or final_report.get("immediate_actions_top3") or []),
                    "artifact_audit_failures": list(fallback_payload.get("artifact_audit_failures") or []),
                }
            )
            self._apply_project_metadata_to_final_report(cowork_id=cowork_id, task_text=task_text, final_report=final_report)
            return final_report

        self._finish_stage_record(
            stage_id=stage_id,
            resolved_status=outcome.status,
            response_text=outcome.response_text,
            error_text=outcome.error_text or outcome.detail,
            outcome=outcome,
        )
        self._store.finish_cowork(
            cowork_id=cowork_id,
            status="failed",
            error_summary=outcome.error_text or outcome.detail or "finalization failed",
        )
        return None

    async def _broadcast_control_command(self, participants: list[dict[str, Any]], command: str) -> None:
        for participant in participants:
            try:
                await self._send_participant_message(participant, command)
            except Exception:
                continue

    async def _broadcast_project_command(self, participants: list[dict[str, Any]], artifact_dir: Path) -> None:
        command = f"/project {artifact_dir}"
        await self._broadcast_control_command(participants, command)

    async def _send_participant_message(self, participant: dict[str, Any], text: str) -> None:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        user_id = int(participant.get("user_id") or 0)
        await self._send_user_message(token, chat_id, user_id, text)

    @staticmethod
    def _participant_scope_key(participant: dict[str, Any]) -> tuple[str, str]:
        bot_id = str(participant.get("bot_id") or "")
        chat_id = str(participant.get("chat_id") or "")
        return (bot_id, chat_id)

    def _max_message_id(self, participant: dict[str, Any]) -> int:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        rows = self._store.get_messages(token=token, chat_id=chat_id, limit=1)
        if not rows:
            return 0
        return int(rows[-1].get("message_id") or 0)

    def _has_turn_activity_since_baseline(self, *, participant: dict[str, Any], baseline_message_id: int) -> bool:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        messages = self._store.get_messages(token=token, chat_id=chat_id, limit=200)
        for message in messages:
            if message.get("direction") != "bot":
                continue
            if int(message.get("message_id") or 0) <= baseline_message_id:
                continue
            text = str(message.get("text") or "").strip().lower()
            if not text:
                continue
            if "queued turn:" in text:
                return True
            if "[thread_started]" in text or "[turn_started]" in text:
                return True
            if "[assistant_message]" in text or "[reasoning]" in text:
                return True
            if "[command_started]" in text or "[command_completed]" in text:
                return True
        return False

    async def _wait_for_turn_result(
        self,
        *,
        cowork_id: str,
        participant: dict[str, Any],
        baseline_message_id: int,
        max_turn_sec: int,
    ) -> TurnOutcome:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        deadline = time.monotonic() + max(1, int(max_turn_sec))

        while time.monotonic() < deadline:
            if self._is_stop_requested(cowork_id):
                return TurnOutcome(done=True, status="stopped", detail="stop_requested", error_text="stop requested")
            outcome = self._classify_turn_outcome(token=token, chat_id=chat_id, baseline_message_id=baseline_message_id)
            if outcome.done:
                return outcome
            await asyncio.sleep(self._poll_interval_sec)

        if self._is_stop_requested(cowork_id):
            return TurnOutcome(done=True, status="stopped", detail="stop_requested", error_text="stop requested")
        last = self._classify_turn_outcome(token=token, chat_id=chat_id, baseline_message_id=baseline_message_id)
        if last.done:
            return last
        return TurnOutcome(done=True, status="timeout", detail="timeout", error_text="turn timeout")

    async def _retry_turn_after_stop(
        self,
        *,
        cowork_id: str,
        participant: dict[str, Any],
        prompt_text: str,
        max_turn_sec: int,
    ) -> TurnOutcome | None:
        try:
            stop_baseline = self._max_message_id(participant)
            await self._send_participant_message(participant, "/stop")
            await self._wait_for_stop_ack(participant=participant, baseline_message_id=stop_baseline, timeout_sec=6)
            baseline = self._max_message_id(participant)
            await self._send_participant_message(participant, prompt_text)
            return await self._wait_for_turn_result(
                cowork_id=cowork_id,
                participant=participant,
                baseline_message_id=baseline,
                max_turn_sec=max_turn_sec,
            )
        except Exception:
            return None

    async def _retry_turn_with_provider_fallback(
        self,
        *,
        cowork_id: str,
        participant: dict[str, Any],
        prompt_text: str,
        max_turn_sec: int,
        fallback_provider: str,
        fallback_model: str | None = None,
    ) -> TurnOutcome | None:
        try:
            stop_baseline = self._max_message_id(participant)
            await self._send_participant_message(participant, "/stop")
            await self._wait_for_stop_ack(participant=participant, baseline_message_id=stop_baseline, timeout_sec=6)

            await self._send_participant_message(participant, f"/mode {fallback_provider}")
            if fallback_model:
                await self._send_participant_message(participant, f"/model {fallback_model}")
            await asyncio.sleep(self._poll_interval_sec)

            normalized_provider = str(fallback_provider or "").strip().lower()
            if normalized_provider:
                participant["adapter"] = normalized_provider

            baseline = self._max_message_id(participant)
            await self._send_participant_message(participant, prompt_text)
            return await self._wait_for_turn_result(
                cowork_id=cowork_id,
                participant=participant,
                baseline_message_id=baseline,
                max_turn_sec=max_turn_sec,
            )
        except Exception:
            return None

    async def _run_turn_with_recovery(
        self,
        *,
        cowork_id: str,
        participant: dict[str, Any],
        prompt_text: str,
        max_turn_sec: int,
        timeout_floor_sec: int = 0,
        max_agent_attempts: int = 1,
        allow_stop_retry: bool = False,
        allow_provider_fallback: bool = True,
    ) -> TurnOutcome:
        effective_timeout = max(int(max_turn_sec), int(timeout_floor_sec))
        attempts = max(1, int(max_agent_attempts))
        baseline = 0
        outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text="unknown")

        for _attempt in range(attempts):
            try:
                baseline = self._max_message_id(participant)
                await self._send_participant_message(participant, prompt_text)
                outcome = await self._wait_for_turn_result(
                    cowork_id=cowork_id,
                    participant=participant,
                    baseline_message_id=baseline,
                    max_turn_sec=effective_timeout,
                )
            except Exception as error:
                outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text=str(error))
            if outcome.status == "success":
                outcome.effective_timeout_sec = effective_timeout
                return outcome
            if outcome.status == "timeout" and self._has_turn_activity_since_baseline(
                participant=participant,
                baseline_message_id=baseline,
            ):
                grace_outcome = await self._wait_for_turn_result(
                    cowork_id=cowork_id,
                    participant=participant,
                    baseline_message_id=baseline,
                    max_turn_sec=max(1, min(2, effective_timeout)),
                )
                if grace_outcome.status == "success":
                    grace_outcome.effective_timeout_sec = effective_timeout
                    return grace_outcome
                outcome = grace_outcome
            if outcome.status == "timeout" and self._is_stop_requested(cowork_id):
                outcome.effective_timeout_sec = effective_timeout
                return outcome

        if allow_stop_retry and (
            outcome.status == "timeout"
            or self._looks_like_active_run_outcome(outcome)
            or self._looks_like_process_exit_outcome(outcome)
            or self._looks_like_stream_timeout_outcome(outcome)
        ):
            retry = await self._retry_turn_after_stop(
                cowork_id=cowork_id,
                participant=participant,
                prompt_text=prompt_text,
                max_turn_sec=effective_timeout,
            )
            if retry is not None:
                outcome = retry
        elif allow_provider_fallback and self._looks_like_gemini_human_input_required_outcome(outcome=outcome, participant=participant):
            retry = await self._retry_turn_with_provider_fallback(
                cowork_id=cowork_id,
                participant=participant,
                prompt_text=prompt_text,
                max_turn_sec=effective_timeout,
                fallback_provider="codex",
                fallback_model="gpt-5",
            )
            if retry is not None:
                outcome = retry
        outcome.effective_timeout_sec = effective_timeout
        return outcome

    async def _wait_for_stop_ack(self, *, participant: dict[str, Any], baseline_message_id: int, timeout_sec: int) -> None:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        deadline = time.monotonic() + max(1, int(timeout_sec))
        while time.monotonic() < deadline:
            messages = self._store.get_messages(token=token, chat_id=chat_id, limit=120)
            for message in messages:
                if message.get("direction") != "bot":
                    continue
                if int(message.get("message_id") or 0) <= baseline_message_id:
                    continue
                text = str(message.get("text") or "").lower()
                if "stop requested." in text or "no active run." in text or "stopping..." in text:
                    return
            await asyncio.sleep(self._poll_interval_sec)

    def _classify_turn_outcome(self, *, token: str, chat_id: int, baseline_message_id: int) -> TurnOutcome:
        messages = self._store.get_messages(token=token, chat_id=chat_id, limit=200)
        bot_messages = [
            message
            for message in messages
            if message.get("direction") == "bot" and int(message.get("message_id") or 0) > baseline_message_id
        ]
        if not bot_messages:
            return TurnOutcome(done=False, status="running", detail="waiting")

        latest_assistant = ""
        latest_fallback = ""
        saw_turn_completed = False
        for message in bot_messages:
            text = str(message.get("text") or "").strip()
            parsed = self._parse_event_text(text)
            if text and not parsed.get("has_event_line"):
                latest_fallback = text
            assistant_text = parsed.get("assistant_text") or ""
            if assistant_text:
                if not latest_assistant:
                    latest_assistant = assistant_text
                elif assistant_text in latest_assistant:
                    pass
                elif latest_assistant in assistant_text:
                    latest_assistant = assistant_text
                else:
                    latest_assistant = f"{latest_assistant}\n{assistant_text}".strip()
            if parsed.get("error_text"):
                return TurnOutcome(done=True, status="error", detail="error_event", error_text=str(parsed["error_text"]))
            if parsed.get("turn_failed"):
                return TurnOutcome(done=True, status="error", detail="turn_failed", error_text=text or "turn failed")
            if parsed.get("turn_completed"):
                saw_turn_completed = True

            lowered = text.lower()
            if self._contains_active_run_hint(lowered):
                return TurnOutcome(done=True, status="error", detail="active_run", error_text=text)
            if any(token_hint in lowered for token_hint in ERROR_HINTS):
                return TurnOutcome(done=True, status="error", detail="error_hint", error_text=text)

        if saw_turn_completed and latest_assistant:
            return TurnOutcome(done=True, status="success", detail="assistant_message", response_text=latest_assistant)
        if saw_turn_completed:
            return TurnOutcome(done=True, status="success", detail="turn_completed", response_text=latest_fallback)
        return TurnOutcome(done=False, status="running", detail="waiting")

    def _parse_event_text(self, text: str) -> dict[str, Any]:
        assistant_parts: list[str] = []
        error_parts: list[str] = []
        turn_completed = False
        turn_failed = False
        current_type = ""
        has_event_line = False
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            event = EVENT_LINE_RE.match(line)
            if event:
                has_event_line = True
                current_type = event.group(3).lower()
                body = event.group(4).strip()
                if current_type == "assistant_message" and body:
                    assistant_parts.append(body)
                elif current_type in {"error", "delivery_error"} and body:
                    error_parts.append(body)
                elif current_type == "turn_completed":
                    turn_completed = True
                    if TURN_FAILED_RE.search(body):
                        turn_failed = True
                    elif TURN_SUCCESS_RE.search(body):
                        turn_failed = False
                continue

            continuation = line.strip()
            if not continuation or not current_type:
                continue
            if current_type == "assistant_message":
                assistant_parts.append(continuation)
            elif current_type in {"error", "delivery_error"}:
                error_parts.append(continuation)

        return {
            "assistant_text": "\n".join(part for part in assistant_parts if part).strip(),
            "error_text": "\n".join(part for part in error_parts if part).strip() or None,
            "turn_completed": turn_completed,
            "turn_failed": turn_failed,
            "has_event_line": has_event_line,
        }

    @staticmethod
    def _contains_active_run_hint(text: str) -> bool:
        lowered = str(text or "").lower()
        return any(hint in lowered for hint in ACTIVE_RUN_HINTS)

    def _looks_like_active_run_outcome(self, outcome: TurnOutcome) -> bool:
        if outcome.status != "error":
            return False
        if str(outcome.detail).strip().lower() == "active_run":
            return True
        return self._contains_active_run_hint(str(outcome.error_text or "").lower())

    @staticmethod
    def _looks_like_stream_timeout_outcome(outcome: TurnOutcome) -> bool:
        haystack = " ".join([str(outcome.detail or ""), str(outcome.error_text or ""), str(outcome.response_text or "")]).lower()
        if not haystack:
            return False
        return any(
            marker in haystack
            for marker in (
                "adapter stream timed out",
                "adapter stream timed out or cancelled",
                "stream timed out",
                "watchdog timeout",
                "turn timed out after",
            )
        )

    def _looks_like_gemini_human_input_required_outcome(self, *, outcome: TurnOutcome, participant: dict[str, Any]) -> bool:
        if outcome.status != "error":
            return False
        provider = str(participant.get("adapter") or "").strip().lower()
        if provider != "gemini":
            return False
        haystack = " ".join(
            [
                str(outcome.detail or ""),
                str(outcome.error_text or ""),
                str(outcome.response_text or ""),
            ]
        ).lower()
        if not haystack:
            return False
        return any(hint in haystack for hint in GEMINI_HUMAN_INPUT_HINTS)

    @staticmethod
    def _looks_like_process_exit_outcome(outcome: TurnOutcome) -> bool:
        if outcome.status != "error":
            return False
        haystack = " ".join([str(outcome.detail or ""), str(outcome.error_text or ""), str(outcome.response_text or "")]).lower()
        if not haystack:
            return False
        return bool(re.search(r"exited\\s+with\\s+code\\s+-?\\d+", haystack))

    def _is_stop_requested(self, cowork_id: str) -> bool:
        cowork = self._store.get_cowork(cowork_id=cowork_id)
        if cowork is None:
            return True
        return bool(cowork.get("stop_requested"))

    def _normalize_roles(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = [{**row} for row in participants]
        reserved = {"controller": False, "planner": False, "qa": False}
        for row in normalized:
            role = self._normalize_role_name(row.get("role") or "implementer")
            if role in reserved:
                if reserved[role]:
                    role = "implementer"
                else:
                    reserved[role] = True
            row["role"] = role

        has_implementer = any(str(row.get("role") or "") == "implementer" for row in normalized)
        if not has_implementer:
            candidate = next((row for row in normalized if str(row.get("role") or "") not in {"planner", "qa", "controller"}), None)
            if candidate is None:
                candidate = normalized[-1]
            candidate["role"] = "implementer"
        return normalized

    def _role_map(self, participants: list[dict[str, Any]]) -> dict[str, Any]:
        controller = next((row for row in participants if str(row.get("role")) == "controller"), None)
        planner = next((row for row in participants if str(row.get("role")) == "planner"), None)
        implementers = [row for row in participants if str(row.get("role")) == "implementer"]
        if controller is None:
            controller = planner or next((row for row in participants if str(row.get("role")) == "qa"), None) or participants[0]
        if planner is None:
            planner = controller or participants[0]
        qa = next((row for row in participants if str(row.get("role")) == "qa"), None)
        if qa is None:
            implementer_ids = {str(row.get("bot_id") or "") for row in implementers}
            qa = next(
                (
                    row
                    for row in [controller, planner, *participants]
                    if row and str(row.get("bot_id") or "") not in implementer_ids
                ),
                None,
            )
        if qa is None:
            qa = controller or planner or participants[-1]
        if not implementers:
            implementers = [planner]
        return {
            "controller": controller,
            "planner": planner,
            "qa": qa,
            "implementers": implementers,
        }

    @staticmethod
    def _same_participant(participant_a: dict[str, Any] | None, participant_b: dict[str, Any] | None) -> bool:
        if not isinstance(participant_a, dict) or not isinstance(participant_b, dict):
            return False
        bot_a = str(participant_a.get("bot_id") or "").strip()
        bot_b = str(participant_b.get("bot_id") or "").strip()
        chat_a = str(participant_a.get("chat_id") or "").strip()
        chat_b = str(participant_b.get("chat_id") or "").strip()
        return bool(bot_a and bot_a == bot_b and chat_a == chat_b)

    def _next_stage_no(self, cowork_id: str) -> int:
        stages = self._store.list_cowork_stages(cowork_id=cowork_id)
        max_no = max((int(row.get("stage_no") or 0) for row in stages), default=0)
        return max_no + 1

    def _assignee_for_owner_role(
        self,
        *,
        owner_role: str,
        role_map: dict[str, Any],
        role_cursors: dict[str, int],
    ) -> dict[str, Any]:
        normalized_owner = self._normalize_role_name(owner_role)
        if normalized_owner == "implementer":
            pool = role_map.get("implementers") if isinstance(role_map.get("implementers"), list) else []
            if not pool:
                return dict(role_map.get("planner") or {})
            cursor = int(role_cursors.get("implementer") or 0)
            picked = pool[cursor % len(pool)]
            role_cursors["implementer"] = cursor + 1
            return dict(picked)
        if normalized_owner == "planner":
            return dict(role_map.get("planner") or role_map.get("controller") or {})
        if normalized_owner == "qa":
            return dict(role_map.get("qa") or role_map.get("planner") or {})
        return dict(role_map.get("controller") or role_map.get("planner") or {})

    @staticmethod
    def _stage_type_for_owner_role(owner_role: str) -> str:
        normalized_owner = str(owner_role or "").strip().lower()
        if normalized_owner == "qa":
            return "qa"
        if normalized_owner == "controller":
            return "controller_gate"
        return "implementation"

    @staticmethod
    def _required_labels_for_stage(stage_type: str) -> tuple[str, ...]:
        normalized_stage = str(stage_type or "").strip().lower()
        if normalized_stage == "qa":
            return QA_REQUIRED_LABELS
        if normalized_stage == "controller_gate":
            return CONTROLLER_GATE_REQUIRED_LABELS
        if normalized_stage == "finalization":
            return FINALIZATION_REQUIRED_LABELS
        return IMPLEMENTATION_REQUIRED_LABELS

    def _fallback_task_response(
        self,
        *,
        cowork_id: str,
        task_text: str,
        stage_type: str,
        plan: dict[str, Any],
    ) -> str | None:
        if self._requires_real_web_artifact(cowork_id=cowork_id, task_text=task_text):
            return None
        scaffold = self._ensure_project_scaffold_if_needed(cowork_id=cowork_id, task_text=task_text)
        audit = self._artifact_audit(cowork_id=cowork_id, task_text=task_text)
        if not scaffold or not audit:
            return None
        entry_url = self._artifact_relative_url(
            cowork_id=cowork_id,
            relative_path=str(audit.get("entry_artifact_path") or "index.html"),
        )
        if stage_type == "qa":
            return synthesize_qa_from_audit(audit)
        if stage_type == "controller_gate":
            gate_result = "APPROVED" if audit.get("passed") else "REJECTED"
            next_actions = [
                "artifact 링크 확인",
                "필수 마커 보강" if not audit.get("passed") else "추가 시각 검수",
                "최종 보고 갱신",
            ]
            return "\n".join(
                [
                    f"게이트결론: {gate_result}",
                    f"게이트체크리스트: entry={entry_url} / files={len(audit.get('required_files') or [])}",
                    f"다음조치(Top3): 1) {next_actions[0]} 2) {next_actions[1]} 3) {next_actions[2]}",
                ]
            )
        title = str(plan.get("title") or "구현 작업")
        summary = "artifact scaffold created" if audit.get("passed") else "artifact scaffold created with follow-up fixes required"
        remaining = "없음" if audit.get("passed") else "; ".join(list(audit.get("artifact_audit_failures") or [])[:2])
        return "\n".join(
            [
                f"결과요약: {title} fallback scaffold generated (source=fallback_scaffold)",
                f"검증: {summary}",
                f"실행링크: {entry_url}",
                "증빙: deterministic web scaffold files generated in artifact directory",
                "테스트요청: artifact route에서 index.html 열기",
                f"남은이슈: {remaining}",
            ]
        )

    @staticmethod
    def _fallback_plan_item(task_text: str) -> dict[str, Any]:
        return {
            "id": "T1",
            "title": "요청 분석 및 실행 초안 작성",
            "goal": f"요청 '{task_text}'에 대한 실행 가능한 초안을 작성",
            "done_criteria": "핵심 작업 단계와 체크리스트를 제시",
            "risk": "요구사항 누락 가능성",
            "owner_role": "implementer",
            "parallel_group": "G1",
            "dependencies": [],
            "artifacts": ["design_spec.md"],
            "estimated_hours": 1.0,
        }

    def _parse_planning_tasks(self, text: str) -> list[dict[str, Any]]:
        submission, _errors = self._parse_planning_submission(text)
        return submission.tasks

    def _parse_planning_submission(self, text: str) -> tuple[PlanningSubmission, list[str]]:
        tasks, errors = self._parse_and_validate_planning_tasks(text)
        path_contract, content_contract = self._extract_planning_doc_contract(text)
        submission = PlanningSubmission(
            tasks=tasks,
            design_doc_path=str(path_contract.get("design_doc_path") or "design_spec.md"),
            qa_plan_path=str(path_contract.get("qa_plan_path") or "qa_test_plan.md"),
            prd_path=str(path_contract.get("prd_path") or "PRD.md"),
            trd_path=str(path_contract.get("trd_path") or "TRD.md"),
            db_path=str(path_contract.get("db_path") or "DB.md"),
            test_strategy_path=str(path_contract.get("test_strategy_path") or "test_strategy.md"),
            release_plan_path=str(path_contract.get("release_plan_path") or "release_plan.md"),
            design_doc_content=content_contract.get("design_doc_content"),
            qa_plan_content=content_contract.get("qa_plan_content"),
            prd_content=content_contract.get("prd_content"),
            trd_content=content_contract.get("trd_content"),
            db_content=content_contract.get("db_content"),
            test_strategy_content=content_contract.get("test_strategy_content"),
            release_plan_content=content_contract.get("release_plan_content"),
        )
        return submission, errors

    @staticmethod
    def _validate_planning_submission(submission: PlanningSubmission, *, require_doc_contents: bool) -> list[str]:
        errors: list[str] = []
        if not submission.tasks:
            errors.append("planning_tasks가 비어 있음")
        return errors

    def _planning_submission_from_payload(self, payload: dict[str, Any]) -> PlanningSubmission:
        return PlanningSubmission(
            tasks=list(payload.get("planning_tasks") or []),
            design_doc_path=str(payload.get("design_doc_path") or "design_spec.md"),
            qa_plan_path=str(payload.get("qa_plan_path") or "qa_test_plan.md"),
            prd_path=str(payload.get("prd_path") or "PRD.md"),
            trd_path=str(payload.get("trd_path") or "TRD.md"),
            db_path=str(payload.get("db_path") or "DB.md"),
            test_strategy_path=str(payload.get("test_strategy_path") or "test_strategy.md"),
            release_plan_path=str(payload.get("release_plan_path") or "release_plan.md"),
            prd_content=str(payload.get("prd_content") or ""),
            trd_content=str(payload.get("trd_content") or ""),
            db_content=str(payload.get("db_content") or ""),
            test_strategy_content=str(payload.get("test_strategy_content") or ""),
            release_plan_content=str(payload.get("release_plan_content") or ""),
            design_doc_content=str(payload.get("design_doc_content") or ""),
            qa_plan_content=str(payload.get("qa_plan_content") or ""),
        )

    def _parse_and_validate_planning_tasks(self, text: str) -> tuple[list[dict[str, Any]], list[str]]:
        payloads = self._extract_planning_payloads(text)
        if not payloads:
            return [], ["planning_tasks가 비어 있거나 JSON 파싱 실패"]
        return self._validate_planning_payloads(payloads)

    @staticmethod
    def _normalize_doc_content(value: Any, *, max_len: int = 12000) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > max_len:
            normalized = normalized[:max_len]
        return normalized

    @staticmethod
    def _extract_json_object_strings(text: str, *, max_objects: int = 8, max_len: int = 120000) -> list[str]:
        source = str(text or "")
        if not source:
            return []
        objects: list[str] = []
        length = len(source)
        idx = 0
        while idx < length and len(objects) < max_objects:
            start = source.find("{", idx)
            if start < 0:
                break
            depth = 0
            in_string = False
            escape = False
            end = -1
            for cursor in range(start, length):
                ch = source[cursor]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = cursor + 1
                        break
            if end > start:
                candidate = source[start:end].strip()
                if candidate and len(candidate) <= max_len:
                    objects.append(candidate)
                idx = end
            else:
                idx = start + 1
        return objects

    @staticmethod
    def _sanitize_json_control_chars(text: str) -> str:
        source = str(text or "")
        if not source:
            return source
        result: list[str] = []
        in_string = False
        escape = False
        for ch in source:
            if in_string:
                if escape:
                    result.append(ch)
                    escape = False
                    continue
                if ch == "\\":
                    result.append(ch)
                    escape = True
                    continue
                if ch == '"':
                    result.append(ch)
                    in_string = False
                    continue
                if ch == "\n":
                    result.append("\\n")
                    continue
                if ch == "\r":
                    result.append("\\r")
                    continue
                if ch == "\t":
                    result.append("\\t")
                    continue
                if ord(ch) < 0x20:
                    result.append(f"\\u{ord(ch):04x}")
                    continue
                result.append(ch)
                continue
            result.append(ch)
            if ch == '"':
                in_string = True
        return "".join(result)

    def _load_json_relaxed(self, candidate: str) -> Any:
        try:
            return json.loads(candidate)
        except Exception:
            sanitized = self._sanitize_json_control_chars(candidate)
            if sanitized != candidate:
                try:
                    return json.loads(sanitized)
                except Exception:
                    return None
            return None

    def _extract_planning_doc_contract(self, text: str) -> tuple[dict[str, str], dict[str, str | None]]:
        default_paths = {
            "design_doc_path": "design_spec.md",
            "qa_plan_path": "qa_test_plan.md",
            "prd_path": "PRD.md",
            "trd_path": "TRD.md",
            "db_path": "DB.md",
            "test_strategy_path": "test_strategy.md",
            "release_plan_path": "release_plan.md",
        }
        default_contents = {
            "design_doc_content": None,
            "qa_plan_content": None,
            "prd_content": None,
            "trd_content": None,
            "db_content": None,
            "test_strategy_content": None,
            "release_plan_content": None,
        }
        stripped = str(text or "").strip()
        if not stripped:
            return dict(default_paths), dict(default_contents)
        candidates = [stripped]
        candidates.extend(
            match.strip()
            for match in re.findall(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
            if match.strip()
        )
        candidates.extend(self._extract_json_object_strings(stripped))
        dedup_candidates = list(dict.fromkeys(candidates))
        for candidate in dedup_candidates:
            loaded = self._load_json_relaxed(candidate)
            if not isinstance(loaded, dict):
                continue
            paths = {
                "design_doc_path": Path(str(loaded.get("design_doc_path") or default_paths["design_doc_path"]).strip() or default_paths["design_doc_path"]).name,
                "qa_plan_path": Path(str(loaded.get("qa_plan_path") or default_paths["qa_plan_path"]).strip() or default_paths["qa_plan_path"]).name,
                "prd_path": Path(str(loaded.get("prd_path") or default_paths["prd_path"]).strip() or default_paths["prd_path"]).name,
                "trd_path": Path(str(loaded.get("trd_path") or default_paths["trd_path"]).strip() or default_paths["trd_path"]).name,
                "db_path": Path(str(loaded.get("db_path") or default_paths["db_path"]).strip() or default_paths["db_path"]).name,
                "test_strategy_path": Path(
                    str(loaded.get("test_strategy_path") or default_paths["test_strategy_path"]).strip()
                    or default_paths["test_strategy_path"]
                ).name,
                "release_plan_path": Path(
                    str(loaded.get("release_plan_path") or default_paths["release_plan_path"]).strip()
                    or default_paths["release_plan_path"]
                ).name,
            }
            contents = {
                "design_doc_content": self._normalize_doc_content(loaded.get("design_doc_content")),
                "qa_plan_content": self._normalize_doc_content(loaded.get("qa_plan_content")),
                "prd_content": self._normalize_doc_content(loaded.get("prd_content")),
                "trd_content": self._normalize_doc_content(loaded.get("trd_content")),
                "db_content": self._normalize_doc_content(loaded.get("db_content")),
                "test_strategy_content": self._normalize_doc_content(loaded.get("test_strategy_content")),
                "release_plan_content": self._normalize_doc_content(loaded.get("release_plan_content")),
            }
            return paths, contents
        return dict(default_paths), dict(default_contents)

    def _extract_planning_payloads(self, text: str) -> list[dict[str, Any]]:
        stripped = str(text or "").strip()
        if not stripped:
            return []

        fenced_matches = re.findall(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
        candidates = [stripped]
        candidates.extend(match.strip() for match in fenced_matches if match.strip())
        candidates.extend(self._extract_json_object_strings(stripped))
        dedup_candidates = list(dict.fromkeys(candidates))

        payloads: list[dict[str, Any]] = []
        for candidate in dedup_candidates:
            loaded: Any = self._load_json_relaxed(candidate)
            if isinstance(loaded, dict):
                if isinstance(loaded.get("planning_tasks"), list):
                    for item in loaded["planning_tasks"]:
                        if isinstance(item, dict):
                            payloads.append(item)
                elif all(key in loaded for key in ("title", "goal", "done_criteria", "risk")):
                    payloads.append(loaded)
            elif isinstance(loaded, list):
                for item in loaded:
                    if isinstance(item, dict):
                        payloads.append(item)
        if payloads:
            deduped: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in payloads:
                marker = (
                    str(item.get("id") or "").strip(),
                    str(item.get("title") or "").strip().lower(),
                    str(item.get("goal") or "").strip().lower(),
                    str(item.get("done_criteria") or item.get("doneCriteria") or "").strip().lower(),
                )
                key = json.dumps(marker, ensure_ascii=False)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            return deduped

        for raw_line in stripped.splitlines():
            line = raw_line.strip()
            if not line or not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads

    def _validate_planning_payloads(self, payloads: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        errors: list[str] = []
        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_titles: set[str] = set()
        signature_seen: set[str] = set()
        raw_by_id: dict[str, dict[str, Any]] = {}

        for index, raw in enumerate(payloads, start=1):
            task_id = str(raw.get("id") or "").strip()
            title = str(raw.get("title") or "").strip()
            goal = str(raw.get("goal") or "").strip()
            done_criteria = str(raw.get("done_criteria") or raw.get("doneCriteria") or "").strip()
            risk = str(raw.get("risk") or "").strip()
            owner_role = str(raw.get("owner_role") or "").strip().lower()
            parallel_group = str(raw.get("parallel_group") or "").strip().upper()
            dependencies_raw = raw.get("dependencies")
            artifacts_raw = raw.get("artifacts")
            estimated_hours_raw = raw.get("estimated_hours")

            if not task_id or not PLANNING_TASK_ID_RE.match(task_id):
                errors.append(f"T{index}: id는 'T숫자' 형식이어야 함")
            if not title:
                errors.append(f"T{index}: title 누락")
            if not goal:
                errors.append(f"T{index}: goal 누락")
            if not done_criteria:
                errors.append(f"T{index}: done_criteria 누락")
            if not risk:
                errors.append(f"T{index}: risk 누락")
            if owner_role not in PLANNING_OWNER_ROLES:
                errors.append(f"{task_id or f'T{index}'}: owner_role은 {PLANNING_OWNER_ROLES} 중 하나여야 함")
            if not parallel_group or not PLANNING_PARALLEL_GROUP_RE.match(parallel_group):
                errors.append(f"{task_id or f'T{index}'}: parallel_group은 'G숫자' 형식이어야 함")

            dependencies: list[str] = []
            if isinstance(dependencies_raw, list):
                dependencies = [str(row).strip() for row in dependencies_raw if str(row).strip()]
            else:
                errors.append(f"{task_id or f'T{index}'}: dependencies는 배열이어야 함")

            artifacts: list[str] = []
            if isinstance(artifacts_raw, list):
                artifacts = [str(row).strip() for row in artifacts_raw if str(row).strip()]
            else:
                errors.append(f"{task_id or f'T{index}'}: artifacts는 배열이어야 함")
            if not artifacts:
                errors.append(f"{task_id or f'T{index}'}: artifacts 최소 1개 필요")

            try:
                estimated_hours = float(estimated_hours_raw)
            except Exception:
                estimated_hours = 0.0
            if estimated_hours <= 0:
                errors.append(f"{task_id or f'T{index}'}: estimated_hours는 0보다 커야 함")

            if task_id:
                if task_id in seen_ids:
                    errors.append(f"{task_id}: 중복 id")
                seen_ids.add(task_id)
            if title:
                title_key = title.lower()
                if title_key in seen_titles:
                    errors.append(f"{title}: 중복 title")
                seen_titles.add(title_key)
            signature = f"{title.lower()}::{goal.lower()}::{done_criteria.lower()}"
            if signature.strip(":") and signature in signature_seen:
                errors.append(f"{task_id or title}: goal/done_criteria 중복")
            signature_seen.add(signature)

            normalized.append(
                {
                    "id": task_id,
                    "title": title,
                    "goal": goal,
                    "done_criteria": done_criteria,
                    "risk": risk,
                    "owner_role": owner_role,
                    "parallel_group": parallel_group,
                    "dependencies": dependencies,
                    "artifacts": artifacts,
                    "estimated_hours": round(estimated_hours, 2),
                }
            )
            if task_id:
                raw_by_id[task_id] = normalized[-1]

        if len(normalized) < 1:
            errors.append("planning_tasks는 최소 1개 이상이어야 함")
        if len(normalized) > 12:
            errors.append("planning_tasks는 최대 12개까지 허용")

        for row in normalized:
            task_id = str(row.get("id") or "")
            deps = row.get("dependencies") if isinstance(row.get("dependencies"), list) else []
            for dep in deps:
                if dep == task_id:
                    errors.append(f"{task_id}: self dependency 금지")
                if dep and dep not in raw_by_id:
                    errors.append(f"{task_id}: unknown dependency '{dep}'")

        if errors:
            return [], errors
        return normalized, []

    def _extract_scenario_inputs(self, task_text: str) -> dict[str, Any]:
        text = str(task_text or "")
        default_project_id = self._derive_project_id(text)
        default_deadline = (date.today() + timedelta(days=14)).isoformat()
        defaults = {
            "project_id": default_project_id,
            "objective": text.strip() or "요구사항 기반 결과물 제공",
            "brand_tone": "신뢰감 있는 프리미엄",
            "target_audience": "온라인 구매 의사가 있는 일반 고객",
            "core_cta": "지금 시작하기",
            "required_sections": ["hero", "product", "trust", "cta"],
            "forbidden_elements": ["과장된 허위 문구"],
            "constraints": ["예산/기간/품질 제약을 명시적으로 관리"],
            "deadline": default_deadline,
            "priority": "P1",
        }
        patterns = {
            "project_id": r"(?:project[_\s-]*id)\s*[:：]\s*([a-zA-Z0-9_-]+)",
            "objective": r"(?:objective|목표)\s*[:：]\s*(.+)",
            "brand_tone": r"(?:브랜드\s*톤|brand\s*tone)\s*[:：]\s*(.+)",
            "target_audience": r"(?:타깃|target(?:\s*audience)?)\s*[:：]\s*(.+)",
            "core_cta": r"(?:핵심\s*cta|core\s*cta)\s*[:：]\s*(.+)",
            "required_sections": r"(?:필수\s*섹션|required\s*sections?)\s*[:：]\s*(.+)",
            "forbidden_elements": r"(?:금지\s*요소|forbidden\s*elements?)\s*[:：]\s*(.+)",
            "constraints": r"(?:constraints?|제약(?:사항)?)\s*[:：]\s*(.+)",
            "deadline": r"(?:deadline|마감(?:일)?)\s*[:：]\s*(\d{4}-\d{2}-\d{2})",
            "priority": r"(?:priority|우선순위)\s*[:：]\s*(P[0-2])",
        }
        result: dict[str, Any] = dict(defaults)
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                loaded = json.loads(stripped)
            except Exception:
                loaded = None
            if isinstance(loaded, dict):
                for key in ("project_id", "objective", "brand_tone", "target_audience", "core_cta", "deadline", "priority"):
                    value = loaded.get(key)
                    if value is not None and str(value).strip():
                        result[key] = str(value).strip()
                for key in ("required_sections", "forbidden_elements", "constraints"):
                    value = loaded.get(key)
                    if isinstance(value, list):
                        normalized = [str(row).strip() for row in value if str(row).strip()]
                        if normalized:
                            result[key] = normalized
        for key, pattern in patterns.items():
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).strip()
            if key in {"required_sections", "forbidden_elements", "constraints"}:
                result[key] = [chunk.strip() for chunk in re.split(r"[,/|]", value) if chunk.strip()] or defaults[key]
            elif key == "project_id":
                normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
                result[key] = normalized or defaults[key]
            elif key == "deadline":
                result[key] = value if re.match(r"^\d{4}-\d{2}-\d{2}$", value) else defaults[key]
            elif key == "priority":
                normalized_priority = value.upper()
                result[key] = normalized_priority if normalized_priority in {"P0", "P1", "P2"} else defaults[key]
            else:
                result[key] = value
        if not str(result.get("project_id") or "").strip():
            result["project_id"] = default_project_id
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(result.get("deadline") or "")):
            result["deadline"] = default_deadline
        if str(result.get("priority") or "").upper() not in {"P0", "P1", "P2"}:
            result["priority"] = "P1"
        return result

    def _derive_project_id(self, text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "").lower()).strip("-")
        if slug:
            return slug[:40]
        digest = hashlib.sha1(str(text or "project").encode("utf-8")).hexdigest()[:8]
        return f"project-{digest}"

    @staticmethod
    def _normalize_project_folder_name(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("._-")
        if normalized:
            return normalized[:80]
        digest = hashlib.sha1(str(value or "project").encode("utf-8")).hexdigest()[:8]
        return f"project-{digest}"

    def _build_planning_prompt(
        self,
        *,
        task_text: str,
        participants: list[dict[str, Any]],
        planner: dict[str, Any],
        scenario: dict[str, Any] | None = None,
        artifact_dir: str | Path | None = None,
        proposal_text: str | None = None,
    ) -> str:
        actor = str(planner.get("label") or planner.get("bot_id") or "Planner")
        roster = ", ".join(
            f"{str(row.get('label') or row.get('bot_id'))}:{str(row.get('role') or 'implementer')}" for row in participants
        )
        normalized_scenario = dict(scenario) if isinstance(scenario, dict) and scenario else self._extract_scenario_inputs(task_text)
        artifact_contract = self._build_artifact_contract_block(artifact_dir)
        proposal_block = f"{str(proposal_text or '').strip()}\n\n" if str(proposal_text or "").strip() else ""
        return (
            "당신은 멀티봇 협업의 Planner입니다.\n"
            f"요청: {task_text}\n"
            f"참여자: {roster}\n"
            f"현재 Planner: {actor}\n\n"
            "[PLAN 기준]\n"
            "- TRD / PRD / Design / DB / Test / Release\n\n"
            "[시나리오 입력]\n"
            f"- project_id: {normalized_scenario['project_id']}\n"
            f"- objective: {normalized_scenario['objective']}\n"
            f"- brand_tone: {normalized_scenario['brand_tone']}\n"
            f"- target_audience: {normalized_scenario['target_audience']}\n"
            f"- core_cta: {normalized_scenario['core_cta']}\n"
            f"- required_sections: {', '.join(normalized_scenario['required_sections'])}\n"
            f"- forbidden_elements: {', '.join(normalized_scenario['forbidden_elements'])}\n\n"
            f"- constraints: {', '.join(normalized_scenario['constraints'])}\n"
            f"- deadline: {normalized_scenario['deadline']}\n"
            f"- priority: {normalized_scenario['priority']}\n\n"
            f"{artifact_contract}"
            f"{proposal_block}"
            "[계약]\n"
            "1) 산출물은 Implementer/QA가 즉시 수행 가능한 작업으로 분해합니다.\n"
            "2) 작업은 id/owner_role/parallel_group/dependencies/artifacts/estimated_hours를 반드시 포함합니다.\n"
            "3) 작업 간 중복/충돌/모호한 표현을 금지합니다.\n"
            "4) required_sections를 누락하지 않도록 task set을 구성합니다.\n\n"
            "5) planning 문서는 반드시 본문을 포함합니다: prd/trd/db/test_strategy/release_plan/design_doc/qa_plan.\n"
            "6) planning fallback은 없습니다. JSON 스키마가 틀리거나 문서 본문이 비면 즉시 실패합니다.\n"
            "7) 작업 수는 1~5개 범위에서 최소 구성으로 작성합니다.\n"
            "8) 응답 지연을 줄이기 위해 각 *_content는 핵심 요약 3~8줄로 간결하게 작성합니다.\n\n"
            "[출력 규격]\n"
            "JSON 객체 1개만 출력합니다. 다른 문장/마크다운/코드블록 금지.\n"
            '{\n'
            '  "planning_tasks": [\n'
            '    {\n'
            '      "id":"T1",\n'
            '      "title":"작업명",\n'
            '      "goal":"목표",\n'
            '      "done_criteria":"완료조건",\n'
            '      "risk":"리스크",\n'
            '      "owner_role":"implementer",\n'
            '      "parallel_group":"G1",\n'
            '      "dependencies":[],\n'
            '      "artifacts":["design_spec.md"],\n'
            '      "estimated_hours":1.5\n'
            "    }\n"
            "  ],\n"
            '  "prd_path":"PRD.md",\n'
            '  "trd_path":"TRD.md",\n'
            '  "db_path":"DB.md",\n'
            '  "test_strategy_path":"test_strategy.md",\n'
            '  "release_plan_path":"release_plan.md",\n'
            '  "design_doc_path":"design_spec.md",\n'
            '  "qa_plan_path":"qa_test_plan.md",\n'
            '  "prd_content":"# PRD ...",\n'
            '  "trd_content":"# TRD ...",\n'
            '  "db_content":"# DB ...",\n'
            '  "test_strategy_content":"# Test Strategy ...",\n'
            '  "release_plan_content":"# Release Plan ...",\n'
            '  "design_doc_content":"# Design Spec ...",\n'
            '  "qa_plan_content":"# QA Test Plan ..."\n'
            "}\n"
            "최소 2개, 최대 8개 작업."
        )

    def _build_planning_rejection_prompt(
        self,
        *,
        task_text: str,
        participants: list[dict[str, Any]],
        planner: dict[str, Any],
        scenario: dict[str, Any] | None,
        feedback_reasons: list[str],
        round_no: int,
        artifact_dir: str | Path | None = None,
        proposal_text: str | None = None,
    ) -> str:
        feedback = "\n".join(f"- {row}" for row in feedback_reasons[:8]) or "- 스키마/검토 기준 미충족"
        base = self._build_planning_prompt(
            task_text=task_text,
            participants=participants,
            planner=planner,
            scenario=scenario,
            artifact_dir=artifact_dir,
            proposal_text=proposal_text,
        )
        return (
            f"{base}\n\n"
            f"[자동 반려 안내]\n"
            f"현재 제출안은 Round {round_no - 1} 검토에서 반려되었습니다.\n"
            "아래 사유를 해소해 planning_tasks를 전면 수정 후 재제출하세요.\n"
            f"{feedback}\n"
            "반드시 동일 출력 규격(JSON 객체 1개)으로만 답변하세요."
        )

    async def _review_planning_plan(
        self,
        *,
        cowork_id: str,
        task_text: str,
        planner: dict[str, Any],
        controller: dict[str, Any],
        plan_items: list[dict[str, Any]],
        max_turn_sec: int,
        round_no: int,
    ) -> PlanningReviewResult:
        if self._same_participant(planner, controller):
            feedback = "dedicated controller absent: planner submission accepted after schema validation"
            stage_id = self._store.insert_cowork_stage_start(
                cowork_id=cowork_id,
                stage_no=self._next_stage_no(cowork_id),
                stage_type="planning_review",
                actor_bot_id=str(controller.get("bot_id") or planner.get("bot_id") or ""),
                actor_label=str(controller.get("label") or planner.get("label") or ""),
                actor_role="controller",
                prompt_text="[auto-approved] no dedicated controller assigned",
            )
            outcome = TurnOutcome(done=True, status="skipped", detail="controller_absent_auto_approve")
            self._finish_stage_record(
                stage_id=stage_id,
                resolved_status="success",
                response_text=feedback,
                outcome=outcome,
            )
            return PlanningReviewResult(approved=True, feedback=feedback)

        prompt_text = self._build_planning_review_prompt(
            task_text=task_text,
            planner=planner,
            controller=controller,
            plan_items=plan_items,
            round_no=round_no,
        )
        stage_id = self._store.insert_cowork_stage_start(
            cowork_id=cowork_id,
            stage_no=self._next_stage_no(cowork_id),
            stage_type="planning_review",
            actor_bot_id=str(controller.get("bot_id") or ""),
            actor_label=str(controller.get("label") or ""),
            actor_role=str(controller.get("role") or "controller"),
            prompt_text=prompt_text,
        )
        outcome = await self._run_turn_with_recovery(
            cowork_id=cowork_id,
            participant=controller,
            prompt_text=prompt_text,
            max_turn_sec=max_turn_sec,
        )
        if outcome.status != "success":
            if outcome.status == "timeout" or self._looks_like_stream_timeout_outcome(outcome):
                self._record_timeout_event(
                    cowork_id=cowork_id,
                    origin="turn_timeout",
                    participant=controller,
                    stage_type="planning_review",
                    effective_timeout_sec=outcome.effective_timeout_sec,
                    detail=outcome.error_text or outcome.detail,
                )
            self._finish_stage_record(
                stage_id=stage_id,
                resolved_status=outcome.status,
                response_text=outcome.response_text,
                error_text=outcome.error_text or outcome.detail,
                outcome=outcome,
            )
            return PlanningReviewResult(
                approved=False,
                feedback=outcome.error_text or outcome.detail or "controller planning review failed",
            )
        parsed = self._parse_planning_review_result(str(outcome.response_text or ""))
        self._finish_stage_record(
            stage_id=stage_id,
            resolved_status="success" if parsed.approved else "failed",
            response_text=outcome.response_text,
            error_text=None if parsed.approved else parsed.feedback,
            outcome=outcome,
        )
        return parsed

    def _build_planning_review_prompt(
        self,
        *,
        task_text: str,
        planner: dict[str, Any],
        controller: dict[str, Any],
        plan_items: list[dict[str, Any]],
        round_no: int,
    ) -> str:
        planner_label = str(planner.get("label") or planner.get("bot_id") or "Planner")
        controller_label = str(controller.get("label") or controller.get("bot_id") or "Controller")
        serialized = json.dumps(plan_items, ensure_ascii=False, indent=2)
        return (
            "당신은 멀티봇 협업의 Controller입니다.\n"
            f"원본 요청: {task_text}\n"
            f"검토 회차: {round_no}\n"
            f"작성자 Bot: {planner_label}\n"
            f"Reviewer: {controller_label}\n\n"
            "[검토 기준]\n"
            "1) planning_tasks JSON 스키마 적합성\n"
            "2) 병렬 가능 분해(parallel_group/dependencies)\n"
            "3) 완료조건/리스크 명확성\n"
            "4) 실무 실행 가능성\n\n"
            "검토 대상 planning_tasks:\n"
            f"{serialized}\n\n"
            "[출력 형식]\n"
            "아래 JSON 객체 1개만 출력:\n"
            '{"decision":"APPROVED|REJECTED","reason":"요약 사유","must_fix":["보강1","보강2"]}'
        )

    def _parse_planning_review_result(self, text: str) -> PlanningReviewResult:
        stripped = str(text or "").strip()
        if stripped:
            try:
                loaded = json.loads(stripped)
            except Exception:
                loaded = None
            if isinstance(loaded, dict):
                decision = str(loaded.get("decision") or "").strip().upper()
                reason = str(loaded.get("reason") or "").strip()
                must_fix_raw = loaded.get("must_fix")
                fixes = must_fix_raw if isinstance(must_fix_raw, list) else []
                fixes_text = "; ".join(str(row).strip() for row in fixes if str(row).strip())
                feedback = reason or fixes_text or "controller review feedback missing"
                if decision == "APPROVED":
                    return PlanningReviewResult(approved=True, feedback=feedback or "approved")
                return PlanningReviewResult(approved=False, feedback=feedback)

        lowered = stripped.lower()
        if "approved" in lowered or "승인" in stripped:
            return PlanningReviewResult(approved=True, feedback="approved")
        if (
            "rejected" in lowered
            or "반려" in stripped
            or "보강" in stripped
            or "미흡" in stripped
            or "불가" in stripped
        ):
            return PlanningReviewResult(approved=False, feedback=stripped or "controller rejected planning")
        if "실행 가능" in stripped and "미이행" not in stripped and "불가" not in stripped:
            return PlanningReviewResult(approved=True, feedback="approved by execution 가능 판정")
        return PlanningReviewResult(approved=False, feedback=stripped or "controller review undecidable")

    def _missing_required_labels(self, *, text: str, required_labels: tuple[str, ...]) -> list[str]:
        if required_labels == QA_REQUIRED_LABELS:
            qa_values = [self._extract_labeled_line(text, label) for label in QA_REQUIRED_LABELS]
            if all(value is not None for value in qa_values):
                return []
            # Backward compatibility: accept legacy Integrator contract fields.
            legacy_summary = self._extract_labeled_line(text, "통합요약")
            legacy_missing = self._extract_labeled_line(text, "누락사항")
            legacy_fix = self._extract_labeled_line(text, "권장수정")
            if legacy_summary is not None and legacy_missing is not None and legacy_fix is not None:
                return []

        missing: list[str] = []
        for label in required_labels:
            value = self._extract_labeled_line(text, label)
            if value is None:
                missing.append(label)
        return missing

    def _build_stage_schema_rejection_prompt(self, *, stage_type: str, missing_labels: list[str]) -> str:
        labels = ", ".join(missing_labels)
        return (
            f"[자동 반려] {stage_type} 출력이 스키마 기준을 충족하지 못했습니다.\n"
            f"누락 필드: {labels}\n"
            "이전 형식을 유지한 채 누락 필드를 보강해 전체 응답을 다시 작성하세요."
        )

    async def _enforce_stage_schema(
        self,
        *,
        cowork_id: str,
        participant: dict[str, Any],
        stage_type: str,
        required_labels: tuple[str, ...],
        max_turn_sec: int,
        outcome: TurnOutcome,
    ) -> TurnOutcome:
        checked = outcome
        for _attempt in range(STAGE_SCHEMA_MAX_RETRIES + 1):
            if checked.status != "success":
                return checked
            missing = self._missing_required_labels(
                text=str(checked.response_text or ""),
                required_labels=required_labels,
            )
            if not missing:
                return checked
            if _attempt >= STAGE_SCHEMA_MAX_RETRIES:
                return TurnOutcome(
                    done=True,
                    status="failed",
                    detail=f"{stage_type}_schema_validation_failed",
                    response_text=checked.response_text,
                    error_text=f"{stage_type} schema validation failed: missing {', '.join(missing)}",
                )
            rejection_prompt = self._build_stage_schema_rejection_prompt(
                stage_type=stage_type,
                missing_labels=missing,
            )
            checked = await self._run_turn_with_recovery(
                cowork_id=cowork_id,
                participant=participant,
                prompt_text=rejection_prompt,
                max_turn_sec=max_turn_sec,
            )
        return checked

    def _build_execution_prompt(
        self,
        *,
        task_text: str,
        task_no: int,
        plan: dict[str, Any],
        assignee: dict[str, Any],
        artifact_dir: str | Path | None = None,
        design_doc_path: str | None = None,
        qa_plan_path: str | None = None,
        design_doc_excerpt: str | None = None,
        qa_plan_excerpt: str | None = None,
        planning_context_excerpt: str | None = None,
    ) -> str:
        design_ref = Path(str(design_doc_path or "design_spec.md")).name
        qa_ref = Path(str(qa_plan_path or "qa_test_plan.md")).name
        artifacts = plan.get("artifacts") if isinstance(plan.get("artifacts"), list) else []
        artifact_line = ", ".join(str(row).strip() for row in artifacts if str(row).strip()) or "없음"
        file_contract = artifact_line if artifact_line != "없음" else "index.html, styles.css, README.md"
        design_excerpt = str(design_doc_excerpt or "").strip().replace("\n", " ")
        qa_excerpt = str(qa_plan_excerpt or "").strip().replace("\n", " ")
        if len(design_excerpt) > 180:
            design_excerpt = f"{design_excerpt[:180]}..."
        if len(qa_excerpt) > 180:
            qa_excerpt = f"{qa_excerpt[:180]}..."
        planning_excerpt = str(planning_context_excerpt or "").strip().replace("\n", " ")
        if len(planning_excerpt) > 260:
            planning_excerpt = f"{planning_excerpt[:260]}..."
        artifact_contract = self._build_artifact_contract_block(artifact_dir)
        return (
            "당신은 멀티봇 협업의 Implementer입니다.\n"
            "Legacy alias: Executor\n"
            f"원본 요청: {task_text}\n"
            f"할당 작업 번호: {task_no}\n"
            f"작업명: {str(plan.get('title') or '')}\n"
            f"목표: {str(plan.get('goal') or '')}\n"
            f"완료조건: {str(plan.get('done_criteria') or '')}\n"
            f"리스크: {str(plan.get('risk') or '')}\n"
            f"담당자: {str(assignee.get('label') or assignee.get('bot_id') or '')}\n\n"
            f"[승인 문서]\n"
            f"- 설계문서: planning/{design_ref}\n"
            f"- QA문서: planning/{qa_ref}\n"
            f"- 요청 산출물: {artifact_line}\n\n"
            f"[문서 요약]\n"
            f"- 계획 컨텍스트: {planning_excerpt or '요약 없음'}\n"
            f"- 설계 핵심: {design_excerpt or '요약 없음'}\n"
            f"- QA 핵심: {qa_excerpt or '요약 없음'}\n\n"
            f"{artifact_contract}"
            "[계약]\n"
            "1) 승인된 설계문서를 기준으로 goal/done_criteria에 직접 대응되는 결과만 제출합니다.\n"
            "2) 근거 없는 완료 선언을 금지합니다.\n"
            "3) QA문서의 테스트 포인트를 기준으로 검증 결과를 작성합니다.\n"
            "4) 실행링크/증빙이 없으면 이유와 대체 검증을 명시합니다.\n"
            "5) 막힌 경우에도 남은이슈에 원인/다음 액션을 남깁니다.\n"
            f"6) 이번 작업은 텍스트 보고만으로 완료되지 않습니다. 반드시 {file_contract} 파일을 실제로 생성/수정합니다.\n"
            "7) fallback placeholder 금지: 'Runnable Cowork Artifact', 'Generated by cowork deterministic web scaffold.' 문구를 산출물에 남기지 마세요.\n"
            "8) 자체 테스트를 위해 서버가 필요하면 foreground로 대기하지 말고 백그라운드 실행 후 검증이 끝나면 즉시 종료하세요. long-running 프로세스 때문에 turn이 반환되지 않으면 실패입니다.\n\n"
            "[출력 형식]\n"
            "반드시 아래 형식으로 작성하세요.\n"
            "결과요약: (핵심 결과)\n"
            "검증: (완료조건 충족 여부)\n"
            "실행링크: (실제 동작 확인 가능한 URL, 없으면 '없음')\n"
            "증빙: (테스트/로그/스크린샷/명령 결과)\n"
            "테스트요청: (QA에게 전달할 재현 가능한 테스트 요청, 없으면 '없음')\n"
            "남은이슈: (없으면 '없음')\n"
            "총 700자 이내."
        )

    def _build_role_task_prompt(
        self,
        *,
        task_text: str,
        task_no: int,
        plan: dict[str, Any],
        assignee: dict[str, Any],
        owner_role: str,
        artifact_dir: str | Path | None = None,
        design_doc_path: str | None = None,
        qa_plan_path: str | None = None,
        design_doc_excerpt: str | None = None,
        qa_plan_excerpt: str | None = None,
        planning_context_excerpt: str | None = None,
    ) -> str:
        normalized_owner = self._normalize_role_name(owner_role)
        design_ref = Path(str(design_doc_path or "design_spec.md")).name
        qa_ref = Path(str(qa_plan_path or "qa_test_plan.md")).name
        design_excerpt = str(design_doc_excerpt or "").strip().replace("\n", " ")
        qa_excerpt = str(qa_plan_excerpt or "").strip().replace("\n", " ")
        if len(design_excerpt) > 180:
            design_excerpt = f"{design_excerpt[:180]}..."
        if len(qa_excerpt) > 180:
            qa_excerpt = f"{qa_excerpt[:180]}..."
        planning_excerpt = str(planning_context_excerpt or "").strip().replace("\n", " ")
        if len(planning_excerpt) > 260:
            planning_excerpt = f"{planning_excerpt[:260]}..."
        artifact_contract = self._build_artifact_contract_block(artifact_dir)
        if normalized_owner == "qa":
            return (
                "당신은 멀티봇 협업의 QA입니다.\n"
                f"원본 요청: {task_text}\n"
                f"할당 작업 번호: {task_no}\n"
                f"작업명: {str(plan.get('title') or '')}\n"
                f"목표: {str(plan.get('goal') or '')}\n"
                f"완료조건: {str(plan.get('done_criteria') or '')}\n"
                f"담당자: {str(assignee.get('label') or assignee.get('bot_id') or '')}\n\n"
                f"[검증 문서]\n"
                f"- 설계문서: planning/{design_ref}\n"
                f"- QA문서: planning/{qa_ref}\n\n"
                f"[문서 요약]\n"
                f"- 계획 컨텍스트: {planning_excerpt or '요약 없음'}\n"
                f"- 설계 핵심: {design_excerpt or '요약 없음'}\n"
                f"- QA 핵심: {qa_excerpt or '요약 없음'}\n\n"
                f"{artifact_contract}"
                "[출력 형식]\n"
                "QA결론: (PASS 또는 FAIL)\n"
                "결함요약: (없으면 '없음')\n"
                "재현절차: (없으면 '없음')\n"
                "수정요청: (없으면 '없음')\n"
                "QA승인: (APPROVED 또는 REJECTED)\n"
                "총 700자 이내."
            )
        if normalized_owner == "controller":
            return (
                "당신은 멀티봇 협업의 Controller입니다.\n"
                f"원본 요청: {task_text}\n"
                f"할당 작업 번호: {task_no}\n"
                f"작업명: {str(plan.get('title') or '')}\n"
                f"목표: {str(plan.get('goal') or '')}\n"
                f"완료조건: {str(plan.get('done_criteria') or '')}\n"
                f"담당자: {str(assignee.get('label') or assignee.get('bot_id') or '')}\n\n"
                f"[검토 문서]\n"
                f"- 설계문서: planning/{design_ref}\n"
                f"- QA문서: planning/{qa_ref}\n\n"
                f"[문서 요약]\n"
                f"- 계획 컨텍스트: {planning_excerpt or '요약 없음'}\n"
                f"- 설계 핵심: {design_excerpt or '요약 없음'}\n"
                f"- QA 핵심: {qa_excerpt or '요약 없음'}\n\n"
                f"{artifact_contract}"
                "[출력 형식]\n"
                "게이트결론: (APPROVED 또는 REJECTED)\n"
                "게이트체크리스트: ...\n"
                "다음조치(Top3): 1) ... 2) ... 3) ...\n"
                "총 700자 이내."
            )
        return self._build_execution_prompt(
            task_text=task_text,
            task_no=task_no,
            plan=plan,
            assignee=assignee,
            artifact_dir=artifact_dir,
            design_doc_path=design_ref,
            qa_plan_path=qa_ref,
            design_doc_excerpt=design_excerpt,
            qa_plan_excerpt=qa_excerpt,
            planning_context_excerpt=planning_excerpt,
        )

    def _build_execution_summary(self, execution_rows: list[dict[str, Any]]) -> str:
        if not execution_rows:
            return "- 실행 결과가 없습니다."
        lines: list[str] = []
        for row in execution_rows:
            status = str(row.get("status") or "unknown")
            body = str(row.get("response_text") or row.get("error_text") or status).strip()
            if len(body) > 240:
                body = f"{body[:240]}..."
            lines.append(
                f"- T{int(row.get('task_no') or 0)} {str(row.get('title') or '')} / {str(row.get('assignee_label') or row.get('assignee_bot_id') or '')} [{status}] {body}"
            )
        return "\n".join(lines)

    def _build_integration_prompt(
        self,
        *,
        task_text: str,
        integrator: dict[str, Any],
        execution_rows: list[dict[str, Any]],
        artifact_dir: str | Path | None = None,
    ) -> str:
        execution_summary = self._build_execution_summary(execution_rows)
        artifact_contract = self._build_artifact_contract_block(artifact_dir)
        return (
            "당신은 멀티봇 협업의 Integrator입니다. (QA 역할)\n"
            f"원본 요청: {task_text}\n"
            f"담당자: {str(integrator.get('label') or integrator.get('bot_id') or '')}\n\n"
            "실행 결과 요약:\n"
            f"{execution_summary}\n\n"
            f"{artifact_contract}"
            "[계약]\n"
            "1) 구현 결과를 QA 관점으로 PASS/FAIL 판정합니다.\n"
            "2) 결함이 있으면 재현절차와 수정요청을 반드시 작성합니다.\n"
            "3) QA승인 값은 APPROVED 또는 REJECTED 중 하나로만 작성합니다.\n\n"
            "[출력 형식]\n"
            "반드시 아래 형식으로 답하세요.\n"
            "QA결론: (PASS 또는 FAIL)\n"
            "결함요약: (없으면 '없음')\n"
            "재현절차: (없으면 '없음')\n"
            "수정요청: (없으면 '없음')\n"
            "QA승인: (APPROVED 또는 REJECTED)\n"
            "총 900자 이내."
        )

    def _build_finalization_prompt(
        self,
        *,
        task_text: str,
        controller: dict[str, Any],
        integration_text: str,
        execution_rows: list[dict[str, Any]],
        artifact_dir: str | Path | None = None,
    ) -> str:
        execution_summary = self._build_execution_summary(execution_rows)
        clipped_integration = integration_text.strip()
        if len(clipped_integration) > 1800:
            clipped_integration = f"{clipped_integration[:1800]}..."
        artifact_contract = self._build_artifact_contract_block(artifact_dir)
        return (
            "당신은 멀티봇 협업의 Controller입니다.\n"
            f"원본 요청: {task_text}\n"
            f"담당자: {str(controller.get('label') or controller.get('bot_id') or '')}\n\n"
            "QA 리포트:\n"
            f"{clipped_integration}\n\n"
            "실행 결과 요약:\n"
            f"{execution_summary}\n\n"
            f"{artifact_contract}"
            "[계약]\n"
            "1) 최종결론에 실행 가능/불가/조건부 여부를 명시합니다.\n"
            "2) 실행체크리스트는 검증 가능한 항목으로 작성합니다.\n"
            "3) 실행링크/증빙요약 누락 시 미완료로 판정합니다.\n"
            "4) 즉시실행항목 Top3는 다음 라운드에서 바로 실행 가능한 문장으로 작성합니다.\n\n"
            "[출력 형식]\n"
            "아래 형식을 정확히 지켜 최종 결론을 작성하세요.\n"
            "최종결론: ...\n"
            "실행체크리스트: ...\n"
            "실행링크: (실제 동작 확인 가능한 URL, 없으면 '없음')\n"
            "증빙요약: (테스트/캡처/로그 근거 요약)\n"
            "즉시실행항목(Top3): 1) ... 2) ... 3) ...\n"
            "총 900자 이내."
        )

    def _extract_labeled_line(self, text: str, label: str) -> str | None:
        key = label.strip().lower()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" in line:
                left, right = line.split(":", 1)
            elif "：" in line:
                left, right = line.split("：", 1)
            else:
                continue
            if left.strip().lower() != key:
                continue
            value = right.strip()
            return value or None
        return None

    def _extract_top3_actions(self, text: str) -> list[str]:
        line = self._extract_labeled_line(text, "즉시실행항목(Top3)") or ""
        if not line:
            return []
        chunks = re.split(r"\s*\d+\)\s*", line)
        actions = [chunk.strip(" -") for chunk in chunks if chunk.strip(" -")]
        return actions[:3]

    def _build_final_report(
        self,
        *,
        integration_text: str,
        finalization_text: str,
        execution_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        qa_conclusion = self._extract_labeled_line(integration_text, "QA결론")
        defect_summary = self._extract_labeled_line(integration_text, "결함요약")
        repro_steps = self._extract_labeled_line(integration_text, "재현절차")
        fix_requests = self._extract_labeled_line(integration_text, "수정요청")
        qa_signoff = self._extract_labeled_line(integration_text, "QA승인")
        # Backward compatibility for legacy integration format.
        integrated_summary = self._extract_labeled_line(integration_text, "통합요약") or qa_conclusion
        conflicts = self._extract_labeled_line(integration_text, "충돌사항")
        missing = self._extract_labeled_line(integration_text, "누락사항") or defect_summary
        recommended_fixes = self._extract_labeled_line(integration_text, "권장수정") or fix_requests
        integration_link = self._extract_labeled_line(integration_text, "증빙링크")
        final_conclusion = self._extract_labeled_line(finalization_text, "최종결론")
        execution_checklist = self._extract_labeled_line(finalization_text, "실행체크리스트")
        execution_link = self._extract_labeled_line(finalization_text, "실행링크")
        evidence_summary = self._extract_labeled_line(finalization_text, "증빙요약")
        actions = self._extract_top3_actions(finalization_text)
        if not integrated_summary:
            integrated_summary = self._fallback_integration_text(execution_rows)
        if not final_conclusion:
            final_conclusion = finalization_text.splitlines()[0].strip() if finalization_text.strip() else "최종 결론 생성 실패"
        if not execution_link:
            execution_link = integration_link or self._extract_first_link(
                "\n".join(
                    [
                        integration_text,
                        finalization_text,
                        *[str(row.get("response_text") or "") for row in execution_rows],
                    ]
                )
            )
        if not qa_signoff:
            has_execution_link = any(
                bool(self._extract_first_link(str(row.get("response_text") or "")))
                for row in execution_rows
                if str(row.get("status") or "") == "success"
            )
            legacy_missing_normalized = str(missing or "").strip().lower()
            explicit_failure_tokens = ("누락", "미제출", "실패", "불가")
            if has_execution_link:
                qa_signoff = "APPROVED"
            elif legacy_missing_normalized in {"없음", "none", "-", "n/a"}:
                qa_signoff = "APPROVED"
            elif any(token in legacy_missing_normalized for token in explicit_failure_tokens):
                qa_signoff = "REJECTED"
            else:
                qa_signoff = "REJECTED"
        defects = self._build_defects_from_qa(
            qa_signoff=qa_signoff,
            defect_summary=defect_summary or missing or "",
            repro_steps=repro_steps or "",
            fix_requests=fix_requests or recommended_fixes or "",
        )
        return {
            "integrated_summary": integrated_summary,
            "conflicts": conflicts or "없음",
            "missing": missing or "없음",
            "recommended_fixes": recommended_fixes or "없음",
            "final_conclusion": final_conclusion,
            "execution_checklist": execution_checklist or "- 완료 기준 검증\n- 누락 사항 재점검\n- 후속 실행 일정 수립",
            "execution_link": execution_link,
            "evidence_summary": evidence_summary or "증빙 요약 없음",
            "qa_conclusion": qa_conclusion or "미기재",
            "qa_signoff": qa_signoff,
            "defect_summary": defect_summary or "없음",
            "repro_steps": repro_steps or "없음",
            "defects": defects,
            "immediate_actions_top3": actions or [
                "핵심 결과를 사용자와 합의",
                "실행 누락 항목을 보완",
                "후속 검증 라운드 예약",
            ],
        }

    def _apply_project_metadata_to_final_report(
        self,
        *,
        cowork_id: str,
        task_text: str,
        final_report: dict[str, Any],
    ) -> None:
        meta = self._cowork_meta(cowork_id)
        profile = self._project_profile_for_cowork(cowork_id=cowork_id, task_text=task_text)
        final_report["project_profile"] = profile
        final_report["scaffold_source"] = self._scaffold_source_for_cowork(cowork_id=cowork_id)
        final_report["planning_gate_status"] = str(meta.get("planning_gate_status") or "")
        audit = self._artifact_audit(cowork_id=cowork_id, task_text=task_text)
        if not audit:
            return
        entry_path = str(audit.get("entry_artifact_path") or "index.html")
        entry_url = self._artifact_relative_url(cowork_id=cowork_id, relative_path=entry_path)
        final_report["entry_artifact_path"] = entry_path
        final_report["entry_artifact_url"] = entry_url
        final_report["artifact_audit_failures"] = list(audit.get("artifact_audit_failures") or [])
        current_execution_link = str(final_report.get("execution_link") or "").strip()
        if not current_execution_link or current_execution_link.lower() in {"없음", "none", "-"} or current_execution_link == entry_path:
            final_report["execution_link"] = entry_url
        if audit.get("passed"):
            normalized_signoff = str(final_report.get("qa_signoff") or "").strip().upper()
            if normalized_signoff not in {"APPROVED", "PASS"}:
                final_report["qa_signoff"] = "APPROVED"
                final_report["qa_conclusion"] = str(final_report.get("qa_conclusion") or "").strip() or "PASS"
            defects = self._extract_defects(final_report)
            soft_artifact_defects = [
                row
                for row in defects
                if str(row.get("severity") or "").strip().lower() not in {"critical", "high"}
                and any(
                    token in str(row.get("summary") or "").strip().lower()
                    for token in ("링크", "artifact", "증빙", "누락", "미제출")
                )
            ]
            if defects and len(soft_artifact_defects) == len(defects):
                final_report["missing"] = "없음"
                final_report["recommended_fixes"] = "없음"
                final_report["defect_summary"] = "없음"
                final_report["repro_steps"] = "없음"
                final_report["defects"] = []

    def _build_defects_from_qa(
        self,
        *,
        qa_signoff: str,
        defect_summary: str,
        repro_steps: str,
        fix_requests: str,
    ) -> list[dict[str, Any]]:
        summary = str(defect_summary or "").strip()
        if not summary or summary.lower() in {"없음", "none", "-", "n/a"}:
            return []
        normalized_signoff = str(qa_signoff or "").strip().upper()
        severity = self._infer_severity(summary=summary, fix_requests=fix_requests)
        status = "open" if normalized_signoff in {"REJECTED", "FAIL"} else "verified"
        return [
            {
                "defect_id": "D-001",
                "severity": severity,
                "summary": summary,
                "steps_to_reproduce": [str(repro_steps or "재현절차 미기재")],
                "expected": "품질 게이트 통과",
                "actual": summary,
                "owner": "implementer",
                "status": status,
            }
        ]

    def _infer_severity(self, *, summary: str, fix_requests: str) -> str:
        text = f"{summary} {fix_requests}".lower()
        if any(hint in text for hint in CRITICAL_SEVERITY_HINTS):
            return "critical"
        if any(hint in text for hint in HIGH_SEVERITY_HINTS):
            return "high"
        if "low" in text or "낮음" in text or "minor" in text:
            return "low"
        return "medium"

    def _normalize_link(self, raw_link: str | None) -> str | None:
        candidate = str(raw_link or "").strip().strip(".,)")
        if not candidate or candidate.lower() in {"없음", "none", "n/a", "-"}:
            return None
        if candidate.startswith("localhost:") or candidate.startswith("127.0.0.1:"):
            return f"http://{candidate}"
        return candidate

    def _extract_first_link(self, text: str) -> str | None:
        for match in LINK_RE.findall(str(text or "")):
            link = self._normalize_link(match)
            if link:
                return link
        return None

    def _is_link_reachable(self, link: str) -> bool:
        candidate = self._normalize_link(link)
        if not candidate:
            return False
        try:
            request = Request(candidate, method="HEAD")
            with urlopen(request, timeout=1.2) as response:
                code = int(getattr(response, "status", 200) or 200)
                return 200 <= code < 400
        except Exception:
            try:
                request = Request(candidate, method="GET")
                with urlopen(request, timeout=1.2) as response:
                    code = int(getattr(response, "status", 200) or 200)
                    return 200 <= code < 400
            except (URLError, ValueError, TimeoutError):
                return False
            except Exception:
                return False

    def _should_strict_link_check(self, link: str | None) -> bool:
        candidate = self._normalize_link(link)
        if not candidate:
            return False
        raw = str(os.getenv("COWORK_STRICT_LINK_CHECK") or "").strip().lower()
        if raw:
            enabled = raw in {"1", "true", "yes", "on"}
        else:
            enabled = True
        if not enabled:
            return False
        parsed = urlparse(candidate)
        host = str(parsed.hostname or "").strip().lower()
        if host in {"127.0.0.1", "localhost"}:
            local_raw = str(os.getenv("COWORK_STRICT_LINK_CHECK_LOCALHOST") or "").strip().lower()
            return local_raw in {"1", "true", "yes", "on"}
        return True

    def _requires_render_link(self, task_text: str) -> bool:
        lowered = str(task_text or "").lower()
        ascii_hints = {"render", "renderer", "game", "games", "tetris", "playable", "ui", "web", "page", "screen", "layout"}
        ascii_tokens = set(re.findall(r"[a-z0-9_]+", lowered))
        if any(hint in ascii_tokens for hint in ascii_hints):
            return True
        korean_hints = ("게임", "테트리스", "플레이", "랜더", "렌더", "화면", "페이지", "웹")
        return any(hint in lowered for hint in korean_hints)

    def _evaluate_completion_gate(
        self,
        *,
        cowork_id: str | None = None,
        task_text: str,
        execution_rows: list[dict[str, Any]],
        final_report: dict[str, Any],
    ) -> QualityGateResult:
        failures: list[str] = []
        requires_render_link = self._requires_render_link(task_text)
        audit = None
        if str(cowork_id or "").strip():
            audit = self._artifact_audit(cowork_id=str(cowork_id), task_text=task_text)
        if str(cowork_id or "").strip() and self._is_web_artifact_authoritative_mode(cowork_id=str(cowork_id), task_text=task_text) and audit:
            final_conclusion = str(final_report.get("final_conclusion") or "").strip()
            execution_checklist = str(final_report.get("execution_checklist") or "").strip()
            qa_signoff = str(final_report.get("qa_signoff") or "").strip().upper()
            defects = self._extract_defects(final_report)
            critical_or_high = [
                row
                for row in defects
                if str(row.get("severity") or "").strip().lower() in {"critical", "high"}
            ]
            execution_link = self._normalize_link(final_report.get("entry_artifact_url")) or self._normalize_link(final_report.get("execution_link"))
            if not audit.get("passed"):
                failures.extend(list(audit.get("artifact_audit_failures") or []))
            if not final_conclusion or "생성 실패" in final_conclusion:
                failures.append("최종결론이 비어 있거나 생성 실패 상태")
            if not execution_checklist:
                failures.append("실행체크리스트가 비어 있음")
            if qa_signoff not in {"APPROVED", "PASS"}:
                failures.append("QA 승인 미통과")
            if critical_or_high:
                failures.append(f"Critical/High 결함 {len(critical_or_high)}건")
            if not execution_link:
                execution_link = self._artifact_relative_url(
                    cowork_id=str(cowork_id),
                    relative_path=str(audit.get("entry_artifact_path") or "index.html"),
                )
            if not execution_link:
                failures.append("entry artifact URL이 비어 있음")
            return QualityGateResult(
                passed=not failures,
                failures=failures,
                requires_render_link=requires_render_link,
                execution_link=execution_link,
            )
        non_success_rows = [row for row in execution_rows if str(row.get("status") or "") != "success"]
        if non_success_rows:
            failures.append(f"실행 태스크 실패/중단 {len(non_success_rows)}건")

        final_conclusion = str(final_report.get("final_conclusion") or "").strip()
        execution_checklist = str(final_report.get("execution_checklist") or "").strip()
        if not final_conclusion or "생성 실패" in final_conclusion:
            failures.append("최종결론이 비어 있거나 생성 실패 상태")
        if not execution_checklist:
            failures.append("실행체크리스트가 비어 있음")
        qa_signoff = str(final_report.get("qa_signoff") or "").strip().upper()
        if qa_signoff not in {"APPROVED", "PASS"}:
            failures.append("QA 승인 미통과")
        defects = self._extract_defects(final_report)
        critical_or_high = [
            row
            for row in defects
            if str(row.get("severity") or "").strip().lower() in {"critical", "high"}
        ]
        if critical_or_high:
            failures.append(f"Critical/High 결함 {len(critical_or_high)}건")
        high_or_critical_open = [
            row
            for row in defects
            if str(row.get("status") or "").strip().lower() == "open"
            if str(row.get("severity") or "").strip().lower() in {"critical", "high"}
        ]
        if high_or_critical_open:
            failures.append(f"Critical/High 열린 결함 {len(high_or_critical_open)}건")

        execution_link = self._normalize_link(final_report.get("execution_link"))
        entry_artifact_url = self._normalize_link(final_report.get("entry_artifact_url"))
        if entry_artifact_url:
            execution_link = entry_artifact_url
        if not execution_link:
            execution_link = self._extract_first_link(
                "\n".join(
                    [
                        final_conclusion,
                        str(final_report.get("integrated_summary") or ""),
                        str(final_report.get("recommended_fixes") or ""),
                        str(final_report.get("evidence_summary") or ""),
                        *[str(row.get("response_text") or "") for row in execution_rows],
                    ]
                )
            )
        task_links: list[str] = []
        for row in execution_rows:
            if str(row.get("status") or "") != "success":
                continue
            link = self._extract_first_link(str(row.get("response_text") or ""))
            normalized = self._normalize_link(link)
            if normalized:
                task_links.append(normalized)
        if not execution_link and task_links:
            execution_link = task_links[0]
        if audit:
            audit_failures = list(audit.get("artifact_audit_failures") or [])
            final_report["artifact_audit_failures"] = audit_failures
            if audit_failures:
                failures.extend(audit_failures)
            if not execution_link:
                execution_link = self._artifact_relative_url(
                    cowork_id=str(cowork_id),
                    relative_path=str(audit.get("entry_artifact_path") or "index.html"),
                )
        if requires_render_link and not execution_link:
            failures.append("렌더링/화면 요청인데 실행 가능한 링크가 없음")
        if self._should_strict_link_check(execution_link) and execution_link and execution_link.startswith("http") and not self._is_link_reachable(execution_link):
            failures.append("실행 링크 접근 불가(실접속 검증 실패)")

        verdict_blob = "\n".join(
            [
                final_conclusion,
                str(final_report.get("integrated_summary") or ""),
                str(final_report.get("evidence_summary") or ""),
            ]
        ).lower()
        if any(hint in verdict_blob for hint in FAILURE_VERDICT_HINTS):
            failures.append("최종결론이 미완료/미이행 상태")

        evidence_blob = "\n".join(
            [str(row.get("response_text") or "") for row in execution_rows]
            + [str(final_report.get("evidence_summary") or "")]
            + [str(final_report.get("recommended_fixes") or "")]
        ).lower()
        if ERR_CONNECTION_REFUSED_HINT in evidence_blob:
            failures.append("실행 링크 접속 실패(ERR_CONNECTION_REFUSED) 흔적 존재")

        return QualityGateResult(
            passed=not failures,
            failures=failures,
            requires_render_link=requires_render_link,
            execution_link=execution_link,
        )

    def _extract_defects(self, final_report: dict[str, Any]) -> list[dict[str, Any]]:
        raw = final_report.get("defects")
        if not isinstance(raw, list):
            return []
        defects: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            defects.append(
                {
                    "defect_id": str(item.get("defect_id") or ""),
                    "severity": str(item.get("severity") or "medium").strip().lower(),
                    "status": str(item.get("status") or "open").strip().lower(),
                    "summary": str(item.get("summary") or "").strip(),
                }
            )
        return defects

    def _build_rework_plan_items(self, *, task_text: str, failures: list[str], round_no: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for index, failure in enumerate(failures[:3], start=1):
            task_id = f"T{round_no}{index}"
            lowered = failure.lower()
            if "링크" in failure or "render" in lowered or "화면" in failure:
                items.append(
                    {
                        "id": task_id,
                        "title": f"R{round_no}-{index} 실행링크 증빙 보강",
                        "goal": "실제 접속 가능한 렌더링 링크와 검증 근거를 확보",
                        "done_criteria": "실행링크(http://127.0.0.1:<port>/...)와 접속 검증 결과 제시",
                        "risk": "로컬 서버 미기동 시 ERR_CONNECTION_REFUSED 재발",
                        "owner_role": "implementer",
                        "parallel_group": "G1",
                        "dependencies": [],
                        "artifacts": ["qa_test_plan.md"],
                        "estimated_hours": 1.0,
                    }
                )
            elif "실패" in failure or "중단" in failure:
                items.append(
                    {
                        "id": task_id,
                        "title": f"R{round_no}-{index} 실패 태스크 재실행",
                        "goal": "실패/중단 태스크를 성공 상태로 복구",
                        "done_criteria": "결과요약/검증/남은이슈 모두 작성 후 status=success 확보",
                        "risk": "동일 원인 재발 시 반복 실패",
                        "owner_role": "implementer",
                        "parallel_group": "G1",
                        "dependencies": [],
                        "artifacts": ["implementation_report_round_N.md"],
                        "estimated_hours": 1.0,
                    }
                )
            else:
                items.append(
                    {
                        "id": task_id,
                        "title": f"R{round_no}-{index} 품질게이트 보강",
                        "goal": failure,
                        "done_criteria": "누락된 증빙과 체크리스트를 포함한 결과 제출",
                        "risk": "증빙 부재로 최종 승인 실패",
                        "owner_role": "implementer",
                        "parallel_group": "G1",
                        "dependencies": [],
                        "artifacts": ["controller_gate_review_round_N.md"],
                        "estimated_hours": 1.0,
                    }
                )
        if not items:
            items.append(
                {
                    "id": f"T{round_no}1",
                    "title": f"R{round_no}-1 결과 검증 보강",
                    "goal": f"요청 '{task_text}'의 완료 증빙 강화",
                    "done_criteria": "실행링크/검증근거/체크리스트를 포함해 재제출",
                    "risk": "최종 보고와 실제 결과 불일치",
                    "owner_role": "implementer",
                    "parallel_group": "G1",
                    "dependencies": [],
                    "artifacts": ["qa_signoff.md"],
                    "estimated_hours": 1.0,
                }
            )
        return items

    def _build_defect_rework_plan_items(self, *, defects: list[dict[str, Any]], round_no: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for index, defect in enumerate(defects[:5], start=1):
            defect_id = str(defect.get("defect_id") or f"D-{index:03d}")
            severity = str(defect.get("severity") or "medium").strip().lower()
            summary = str(defect.get("summary") or "결함 요약 없음").strip()
            items.append(
                {
                    "id": f"T{round_no}{index}",
                    "title": f"R{round_no}-{index} {defect_id} 결함 수정",
                    "goal": summary,
                    "done_criteria": "재현절차 기준 수정 완료 + QA승인 APPROVED 확보",
                    "risk": f"{severity} 결함 재발",
                    "owner_role": "implementer",
                    "parallel_group": "G1",
                    "dependencies": [],
                    "artifacts": ["defect_report_round_1.json", "qa_signoff.md"],
                    "estimated_hours": 1.0,
                }
            )
        return items or [
            {
                "id": f"T{round_no}1",
                "title": f"R{round_no}-1 결함 재검증 보강",
                "goal": "QA 결함 해소 확인",
                "done_criteria": "결함 0건 및 QA 승인 통과",
                "risk": "결함 누락",
                "owner_role": "implementer",
                "parallel_group": "G1",
                "dependencies": [],
                "artifacts": ["qa_signoff.md"],
                "estimated_hours": 1.0,
            }
        ]

    def _build_rework_task_text(self, *, task_text: str, failures: list[str], round_no: int, proposal_text: str | None = None) -> str:
        failure_lines = "\n".join(f"- {row}" for row in failures[:5]) or "- 미정의 품질 이슈"
        base = (
            f"{task_text}\n"
            f"[보강 라운드 {round_no}] 품질 게이트 미통과 이슈를 해소하세요.\n"
            "아래 이슈를 모두 반영하고, 실행링크/검증근거를 반드시 포함해 답변하세요.\n"
            f"{failure_lines}"
        )
        if str(proposal_text or "").strip():
            return f"{base}\n\n{str(proposal_text).strip()}"
        return base

    def _fallback_integration_text(self, execution_rows: list[dict[str, Any]]) -> str:
        summary = self._build_execution_summary(execution_rows)
        return (
            "QA결론: FAIL\n"
            f"결함요약: {summary}\n"
            "재현절차: 워커 실행 로그를 기준으로 재현 필요\n"
            "수정요청: 실패 작업 재실행 및 증빙 보강\n"
            "QA승인: REJECTED"
        )

    def _fallback_finalization_text(self, task_text: str, execution_rows: list[dict[str, Any]]) -> str:
        success_count = sum(1 for row in execution_rows if str(row.get("status") or "") == "success")
        total_count = len(execution_rows)
        return (
            f"최종결론: '{task_text}' 작업은 {success_count}/{total_count} 항목 완료 상태입니다.\n"
            "실행체크리스트: 1) 완료 항목 검증 2) 실패 항목 재시도 3) 통합 리포트 확정\n"
            "즉시실행항목(Top3): 1) 실패 작업 재실행 2) 누락사항 보완 3) 최종 승인"
        )

    def _record_intake_stage(self, *, cowork_id: str, task_text: str, controller: dict[str, Any]) -> None:
        stage_id = self._store.insert_cowork_stage_start(
            cowork_id=cowork_id,
            stage_no=self._next_stage_no(cowork_id),
            stage_type="intake",
            actor_bot_id=str(controller.get("bot_id") or ""),
            actor_label=str(controller.get("label") or ""),
            actor_role=str(controller.get("role") or "controller"),
            prompt_text=f"[intake] {task_text}",
        )
        self._store.finish_cowork_stage(
            stage_id=stage_id,
            status="success",
            response_text="요청 접수 및 역할 배정 완료",
        )

    def _record_rework_stage(
        self,
        *,
        cowork_id: str,
        controller: dict[str, Any],
        round_no: int,
        failures: list[str],
    ) -> None:
        details = "; ".join(failures[:5]) or "quality gate 미통과"
        stage_id = self._store.insert_cowork_stage_start(
            cowork_id=cowork_id,
            stage_no=self._next_stage_no(cowork_id),
            stage_type="rework",
            actor_bot_id=str(controller.get("bot_id") or ""),
            actor_label=str(controller.get("label") or ""),
            actor_role=str(controller.get("role") or "controller"),
            prompt_text=f"[rework-round-{round_no}] {details}",
        )
        self._store.finish_cowork_stage(
            stage_id=stage_id,
            status="success",
            response_text=f"보강 라운드 {round_no} 시작: {details}",
        )

    def _project_id_for_cowork(self, cowork_id: str) -> str:
        cached = self._project_meta_cache.get(cowork_id, {})
        project_id = str(cached.get("project_id") or "").strip()
        if project_id:
            normalized = self._normalize_project_folder_name(project_id)
            if normalized != project_id:
                cached["project_id"] = normalized
                self._project_meta_cache[cowork_id] = cached
            return normalized
        cowork = self._store.get_cowork(cowork_id=cowork_id)
        task_text = str(cowork.get("task") or "") if isinstance(cowork, dict) else ""
        scenario = self._extract_scenario_inputs(task_text)
        derived = self._normalize_project_folder_name(str(scenario.get("project_id") or cowork_id).strip() or cowork_id)
        self._project_meta_cache[cowork_id] = {"project_id": derived}
        return derived

    def _artifact_dir(self, cowork_id: str) -> Path:
        return self._artifact_root / self._project_id_for_cowork(cowork_id) / cowork_id

    def _ensure_artifact_workspace(self, cowork_id: str) -> Path:
        root = self._artifact_dir(cowork_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _build_artifact_contract_block(artifact_dir: str | Path | None) -> str:
        normalized = str(artifact_dir or "").strip()
        if not normalized:
            return ""
        return (
            "[산출물 경로 계약]\n"
            f"- 이번 코워크 결과 경로: {normalized}\n"
            "- 새 파일/수정 파일은 위 경로 기준으로 생성합니다.\n"
            "- 상대 경로를 사용할 때도 위 경로를 기준으로 해석합니다.\n"
            "- 응답 텍스트만 제출하면 실패입니다. 실제 파일 생성/수정이 필요합니다.\n"
            "- 산출물은 placeholder가 아니라 실제 실행 가능한 내용이어야 합니다.\n"
            "- 장기 실행 프로세스(예: python -m http.server, npm run dev, vite)는 foreground로 실행하지 마세요. 필요하면 백그라운드로 띄우고 검증 후 종료하세요.\n\n"
        )

    def _artifact_read_dir(self, cowork_id: str) -> Path:
        preferred = self._artifact_dir(cowork_id)
        if preferred.is_dir():
            return preferred
        legacy = self._artifact_root / self._project_id_for_cowork(cowork_id)
        if legacy.is_dir():
            return legacy
        return preferred

    def _build_artifact_payload(self, cowork_id: str) -> dict[str, Any] | None:
        root = self._artifact_read_dir(cowork_id)
        if not root.is_dir():
            return None
        files: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*"), key=lambda row: str(row.relative_to(root))):
            if not path.is_file():
                continue
            relative_path = str(path.relative_to(root))
            files.append(
                {
                    "name": relative_path,
                    "path": str(path),
                    "url": f"/_mock/cowork/{cowork_id}/artifact/{relative_path}",
                    "size_bytes": int(path.stat().st_size),
                }
            )
        if not files:
            return None
        return {"root_dir": str(root), "files": files}

    def _write_cowork_artifacts(self, cowork_id: str) -> None:
        snapshot = self.get_cowork_snapshot(cowork_id)
        if snapshot is None:
            return
        root = self._ensure_artifact_workspace(cowork_id)

        result_json = root / "result.json"
        result_json.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        final_report = snapshot.get("final_report")
        if isinstance(final_report, dict):
            (root / "final_report.json").write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")

        stages = snapshot.get("stages")
        if isinstance(stages, list):
            (root / "stages.json").write_text(json.dumps(stages, ensure_ascii=False, indent=2), encoding="utf-8")

        tasks = snapshot.get("tasks")
        if isinstance(tasks, list):
            (root / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

        summary_payload = {
            "cowork_id": str(snapshot.get("cowork_id") or ""),
            "status": str(snapshot.get("status") or ""),
            "task": str(snapshot.get("task") or ""),
            "final_report": snapshot.get("final_report") if isinstance(snapshot.get("final_report"), dict) else {},
        }
        (root / "summary.md").write_text(
            "# Artifact Summary (Source-Based)\n\n"
            "```json\n"
            f"{json.dumps(summary_payload, ensure_ascii=False, indent=2)}\n"
            "```\n",
            encoding="utf-8",
        )
        self._write_workflow_documents(cowork_id=cowork_id, snapshot=snapshot, root=root)

    def _write_workflow_documents(self, *, cowork_id: str, snapshot: dict[str, Any], root: Path) -> None:
        planning_dir = root / "planning"
        implementation_dir = root / "implementation"
        qa_dir = root / "qa"
        final_dir = root / "final"
        for directory in (planning_dir, implementation_dir, qa_dir, final_dir):
            directory.mkdir(parents=True, exist_ok=True)

        task_text = str(snapshot.get("task") or "")
        stages = snapshot.get("stages") if isinstance(snapshot.get("stages"), list) else []
        tasks = snapshot.get("tasks") if isinstance(snapshot.get("tasks"), list) else []
        final_report = snapshot.get("final_report") if isinstance(snapshot.get("final_report"), dict) else {}

        planning_stage = next((row for row in reversed(stages) if str(row.get("stage_type") or "") == "planning"), None)
        planning_text = str(planning_stage.get("response_text") or "") if isinstance(planning_stage, dict) else ""
        planning_submission, _ = self._parse_planning_submission(planning_text)
        planning_tasks = planning_submission.tasks
        planning_meta = self._planning_meta_cache.get(cowork_id, {})
        design_doc_path = Path(str(planning_meta.get("design_doc_path") or planning_submission.design_doc_path or "design_spec.md")).name
        qa_plan_path = Path(str(planning_meta.get("qa_plan_path") or planning_submission.qa_plan_path or "qa_test_plan.md")).name
        prd_path = Path(str(planning_meta.get("prd_path") or planning_submission.prd_path or "PRD.md")).name
        trd_path = Path(str(planning_meta.get("trd_path") or planning_submission.trd_path or "TRD.md")).name
        db_path = Path(str(planning_meta.get("db_path") or planning_submission.db_path or "DB.md")).name
        test_strategy_path = Path(
            str(planning_meta.get("test_strategy_path") or planning_submission.test_strategy_path or "test_strategy.md")
        ).name
        release_plan_path = Path(
            str(planning_meta.get("release_plan_path") or planning_submission.release_plan_path or "release_plan.md")
        ).name

        def _doc_from_planner(primary: Any, fallback: Any) -> str:
            direct = self._normalize_doc_content(primary)
            if direct:
                return direct
            secondary = self._normalize_doc_content(fallback)
            if secondary:
                return secondary
            raw = self._normalize_doc_content(planning_text, max_len=50000)
            if raw:
                return raw
            return ""

        prd_content = _doc_from_planner(planning_meta.get("prd_content"), planning_submission.prd_content)
        trd_content = _doc_from_planner(planning_meta.get("trd_content"), planning_submission.trd_content)
        db_content = _doc_from_planner(planning_meta.get("db_content"), planning_submission.db_content)
        test_strategy_content = _doc_from_planner(
            planning_meta.get("test_strategy_content"),
            planning_submission.test_strategy_content,
        )
        release_plan_content = _doc_from_planner(
            planning_meta.get("release_plan_content"),
            planning_submission.release_plan_content,
        )
        design_doc_content = _doc_from_planner(
            planning_meta.get("design_doc_content"),
            planning_submission.design_doc_content,
        )
        qa_plan_content = _doc_from_planner(
            planning_meta.get("qa_plan_content"),
            planning_submission.qa_plan_content,
        )

        (planning_dir / "planning_tasks.json").write_text(
            json.dumps({"planning_tasks": planning_tasks}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        scenario = self._scenario_for_cowork(cowork_id=cowork_id, task_text=task_text)
        planning_prompt_text = str(planning_stage.get("prompt_text") or "") if isinstance(planning_stage, dict) else ""
        (planning_dir / "controller_kickoff.md").write_text(
            "# Controller Kickoff (Source-Based)\n\n"
            "## Prompt\n\n"
            "```text\n"
            f"{planning_prompt_text.strip()}\n"
            "```\n\n"
            "## Scenario\n\n"
            "```json\n"
            f"{json.dumps(scenario, ensure_ascii=False, indent=2)}\n"
            "```\n",
            encoding="utf-8",
        )
        (planning_dir / prd_path).write_text(prd_content, encoding="utf-8")
        (planning_dir / trd_path).write_text(trd_content, encoding="utf-8")
        (planning_dir / db_path).write_text(db_content, encoding="utf-8")
        (planning_dir / test_strategy_path).write_text(test_strategy_content, encoding="utf-8")
        (planning_dir / release_plan_path).write_text(release_plan_content, encoding="utf-8")
        (planning_dir / design_doc_path).write_text(
            design_doc_content,
            encoding="utf-8",
        )
        (planning_dir / qa_plan_path).write_text(
            qa_plan_content,
            encoding="utf-8",
        )
        review_rows = self._planning_review_cache.get(cowork_id, [])
        (planning_dir / "controller_review_rounds.md").write_text(
            "# Controller Review Rounds (Source-Based)\n\n"
            "```json\n"
            f"{json.dumps(review_rows, ensure_ascii=False, indent=2)}\n"
            "```\n",
            encoding="utf-8",
        )
        for row in review_rows:
            round_no = int(row.get("round") or 0)
            if round_no <= 0:
                continue
            (planning_dir / f"controller_gate_review_round_{round_no}.md").write_text(
                "# Controller Gate Review (Source-Based)\n\n"
                "```json\n"
                f"{json.dumps(row, ensure_ascii=False, indent=2)}\n"
                "```\n",
                encoding="utf-8",
            )
        planning_failed_reason = self._detect_planning_failure_reason(snapshot=snapshot, stages=stages)
        if planning_failed_reason:
            (planning_dir / "planning_failed.md").write_text(
                "# Planning Failed (Source-Based)\n\n"
                f"- reason: {planning_failed_reason}\n\n"
                "## Review Rounds\n\n"
                "```json\n"
                f"{json.dumps(review_rows, ensure_ascii=False, indent=2)}\n"
                "```\n",
                encoding="utf-8",
            )

        tasks_by_round: dict[int, list[dict[str, Any]]] = {}
        for row in tasks:
            spec = row.get("spec_json") if isinstance(row.get("spec_json"), dict) else {}
            round_no = int(spec.get("_round_no") or 1)
            tasks_by_round.setdefault(max(1, round_no), []).append(row)
        if not tasks_by_round:
            tasks_by_round = {1: tasks}
        for round_no in sorted(tasks_by_round):
            round_tasks = tasks_by_round.get(round_no, [])
            implementation_lines = [
                f"# Implementation Evidence Round {round_no}",
                "",
                f"- task_count: {len(round_tasks)}",
                "",
            ]
            for row in round_tasks:
                task_no = int(row.get("task_no") or 0)
                title = str(row.get("title") or "")
                assignee = str(row.get("assignee_label") or row.get("assignee_bot_id") or "")
                status = str(row.get("status") or "unknown")
                response = str(row.get("response_text") or row.get("error_text") or "").strip()
                implementation_lines.extend(
                    [
                        f"## T{task_no} {title}",
                        f"- assignee: {assignee}",
                        f"- status: {status}",
                        "",
                        "```text",
                        response,
                        "```",
                        "",
                    ]
                )
            (implementation_dir / f"implementation_report_round_{round_no}.md").write_text(
                "\n".join(implementation_lines).strip() + "\n",
                encoding="utf-8",
            )
            execution_log = [
                {
                    "task_no": int(row.get("task_no") or 0),
                    "title": str(row.get("title") or ""),
                    "assignee": str(row.get("assignee_label") or row.get("assignee_bot_id") or ""),
                    "status": str(row.get("status") or "unknown"),
                    "response_text": str(row.get("response_text") or ""),
                    "error_text": str(row.get("error_text") or ""),
                }
                for row in round_tasks
            ]
            (implementation_dir / f"test_execution_log_round_{round_no}.md").write_text(
                "# Test Execution Log (Source-Based)\n\n"
                "```json\n"
                f"{json.dumps(execution_log, ensure_ascii=False, indent=2)}\n"
                "```\n",
                encoding="utf-8",
            )

        quality_failures = list(final_report.get("quality_gate_failures") or [])
        qa_stage_rows = [row for row in stages if str(row.get("stage_type") or "") == "qa"]
        if qa_stage_rows:
            for round_no, qa_stage in enumerate(qa_stage_rows, start=1):
                qa_text = str(qa_stage.get("response_text") or "")
                qa_defects = self._extract_defects_from_qa_text(qa_text)
                qa_failures = [] if not qa_defects else [str(row.get("summary") or "qa defect") for row in qa_defects]
                (qa_dir / f"qa_result_round_{round_no}.md").write_text(
                    "# QA Result (Source-Based)\n\n"
                    f"- round: {round_no}\n"
                    f"- actor: {str(qa_stage.get('actor_label') or qa_stage.get('actor_bot_id') or '')}\n"
                    f"- stage_status: {str(qa_stage.get('status') or '')}\n\n"
                    "## QA Response\n\n"
                    "```text\n"
                    f"{qa_text.strip()}\n"
                    "```\n\n"
                    "## Parsed Defects\n\n"
                    "```json\n"
                    f"{json.dumps(qa_defects, ensure_ascii=False, indent=2)}\n"
                    "```\n\n"
                    "## Parsed Failures\n\n"
                    "```json\n"
                    f"{json.dumps(qa_failures, ensure_ascii=False, indent=2)}\n"
                    "```\n",
                    encoding="utf-8",
                )
                (qa_dir / f"defect_report_round_{round_no}.json").write_text(
                    json.dumps(qa_defects, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        else:
            defects = final_report.get("defects") if isinstance(final_report.get("defects"), list) else []
            if not defects:
                defects = self._build_defect_report_json(quality_failures)
            (qa_dir / "qa_result_round_1.md").write_text(
                "# QA Result (Source-Based)\n\n"
                "## Final Report Derived Defects\n\n"
                "```json\n"
                f"{json.dumps(defects, ensure_ascii=False, indent=2)}\n"
                "```\n\n"
                "## Quality Failures\n\n"
                "```json\n"
                f"{json.dumps(quality_failures, ensure_ascii=False, indent=2)}\n"
                "```\n",
                encoding="utf-8",
            )
            (qa_dir / "defect_report_round_1.json").write_text(
                json.dumps(defects, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        latest_qa_text = str(qa_stage_rows[-1].get("response_text") or "") if qa_stage_rows else ""
        qa_signoff_value = (
            self._extract_labeled_line(latest_qa_text, "QA승인")
            or str(final_report.get("qa_signoff") or "").strip()
            or ("APPROVED" if not quality_failures and str(snapshot.get("status") or "") == "completed" else "REJECTED")
        )
        (qa_dir / "qa_signoff.md").write_text(
            "# QA Signoff (Source-Based)\n\n"
            f"- qa_signoff: {qa_signoff_value}\n"
            f"- snapshot_status: {str(snapshot.get('status') or '')}\n\n"
            "## Quality Failures\n\n"
            "```json\n"
            f"{json.dumps(quality_failures, ensure_ascii=False, indent=2)}\n"
            "```\n",
            encoding="utf-8",
        )

        final_stage = next((row for row in reversed(stages) if str(row.get("stage_type") or "") == "finalization"), None)
        final_text = str(final_stage.get("response_text") or "") if isinstance(final_stage, dict) else ""
        (final_dir / "controller_final_report.md").write_text(
            "# Controller Final Report (Source-Based)\n\n"
            "## Finalization Response\n\n"
            "```text\n"
            f"{final_text.strip()}\n"
            "```\n\n"
            "## Final Report JSON\n\n"
            "```json\n"
            f"{json.dumps(final_report, ensure_ascii=False, indent=2)}\n"
            "```\n",
            encoding="utf-8",
        )
        workflow_trace = self._build_workflow_trace_rows(snapshot=snapshot)
        (final_dir / "workflow_trace.json").write_text(
            json.dumps(workflow_trace, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (final_dir / "workflow_relational.md").write_text(
            "# Workflow Relational (Source-Based)\n\n"
            "```json\n"
            f"{json.dumps(workflow_trace, ensure_ascii=False, indent=2)}\n"
            "```\n",
            encoding="utf-8",
        )

    def _detect_planning_failure_reason(self, *, snapshot: dict[str, Any], stages: list[dict[str, Any]]) -> str | None:
        status = str(snapshot.get("status") or "").strip().lower()
        if status != "failed":
            return None
        planning_stage = next((row for row in reversed(stages) if str(row.get("stage_type") or "") == "planning"), None)
        if not isinstance(planning_stage, dict):
            return None
        planning_status = str(planning_stage.get("status") or "").strip().lower()
        if planning_status not in {"failed", "error", "timeout"}:
            return None
        reason = str(planning_stage.get("error_text") or snapshot.get("error_summary") or "").strip()
        return reason or "planning 단계가 기준을 충족하지 못했습니다."

    def _extract_defects_from_qa_text(self, text: str) -> list[dict[str, Any]]:
        qa_signoff = self._extract_labeled_line(text, "QA승인") or "REJECTED"
        defect_summary = self._extract_labeled_line(text, "결함요약") or "없음"
        repro_steps = self._extract_labeled_line(text, "재현절차") or "없음"
        fix_requests = self._extract_labeled_line(text, "수정요청") or "없음"
        return self._build_defects_from_qa(
            qa_signoff=qa_signoff,
            defect_summary=defect_summary,
            repro_steps=repro_steps,
            fix_requests=fix_requests,
        )

    def _build_defect_report_json(self, quality_failures: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, failure in enumerate(quality_failures, start=1):
            severity = self._infer_severity(summary=failure, fix_requests="")
            rows.append(
                {
                    "defect_id": f"D-{index:03d}",
                    "severity": severity,
                    "summary": failure,
                    "steps_to_reproduce": ["cowork 실행", "결과 검증"],
                    "expected": "품질 게이트 통과",
                    "actual": failure,
                    "evidence": [],
                    "owner": "implementer",
                    "status": "open",
                }
            )
        return rows

    def _build_workflow_trace_rows(self, *, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        stages = snapshot.get("stages") if isinstance(snapshot.get("stages"), list) else []
        tasks = snapshot.get("tasks") if isinstance(snapshot.get("tasks"), list) else []
        final_report = snapshot.get("final_report") if isinstance(snapshot.get("final_report"), dict) else {}
        status = str(snapshot.get("status") or "")
        planning_review_rounds = len(self._planning_review_cache.get(str(snapshot.get("cowork_id") or ""), []))
        qa_stage_count = sum(1 for row in stages if str(row.get("stage_type") or "") == "qa")
        rework_count = sum(1 for row in stages if str(row.get("stage_type") or "") == "rework")
        has_controller_gate = any(str(row.get("stage_type") or "") == "controller_gate" for row in stages)
        qa_signoff = str(final_report.get("qa_signoff") or "").strip().upper()
        qa_approved = qa_signoff in {"APPROVED", "PASS"}

        return [
            {
                "step": 1,
                "from_to": "User -> Controller",
                "expected_output": "목표/범위/우선순위",
                "status": "done" if any(str(row.get("stage_type") or "") == "intake" for row in stages) else "missing",
            },
            {
                "step": 2,
                "from_to": "Controller -> Planner",
                "expected_output": "PLAN 기준 분석 요청",
                "status": "done" if any(str(row.get("stage_type") or "") == "planning" for row in stages) else "missing",
            },
            {
                "step": 3,
                "from_to": "Planner -> Controller",
                "expected_output": "planning_tasks + 설계/QA 문서",
                "status": "done" if any(str(row.get("stage_type") or "") == "planning_review" for row in stages) else "missing",
            },
            {
                "step": 4,
                "from_to": "Controller -> Planner",
                "expected_output": "검토/보강 루프",
                "status": "done" if planning_review_rounds > 0 else "missing",
                "rounds": planning_review_rounds,
            },
            {
                "step": 5,
                "from_to": "Controller -> Implementer",
                "expected_output": "승인 설계 기반 구현 지시",
                "status": "done" if bool(tasks) else "missing",
            },
            {
                "step": 6,
                "from_to": "Implementer -> Controller/QA",
                "expected_output": "구현 완료 보고 + 테스트 요청",
                "status": "done" if any(str(row.get("stage_type") or "") == "implementation" for row in stages) else "missing",
            },
            {
                "step": 7,
                "from_to": "QA -> Implementer",
                "expected_output": "결함 문서/수정 요청",
                "status": "done" if qa_stage_count > 0 else "missing",
                "qa_rounds": qa_stage_count,
            },
            {
                "step": 8,
                "from_to": "Implementer -> QA",
                "expected_output": "수정 반영/재검증 반복",
                "status": "done" if rework_count > 0 else "skipped",
                "rework_rounds": rework_count,
            },
            {
                "step": 9,
                "from_to": "QA -> Controller",
                "expected_output": "QA 승인서",
                "status": "done" if qa_approved else ("incomplete" if has_controller_gate or qa_stage_count > 0 else "missing"),
                "qa_signoff": qa_signoff or "N/A",
            },
            {
                "step": 10,
                "from_to": "Controller -> User",
                "expected_output": "최종 완료 보고서",
                "status": "done" if status in {"completed", "failed", "stopped"} else "missing",
            },
        ]
