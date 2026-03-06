#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CaseSummary:
    case_no: int
    case_id: str
    task: str
    expected_profile: str
    cowork_id: str
    status: str
    completion_status: str
    qa_signoff: str
    execution_link: str
    entry_artifact_url: str
    project_profile: str
    planning_gate_status: str
    tasks: int
    stages: int
    errors: int
    copied_artifacts: int
    timed_out: bool
    requested_case_timeout_sec: int
    applied_case_timeout_sec: int
    budget_floor_sec: int
    budget_auto_raised: bool
    stop_reason: str
    stop_source: str
    timeout_origin: str
    timeout_actor_label: str
    timeout_actor_role: str
    timeout_stage_type: str
    error_summary: str
    gate_failures: list[str]
    screenshots: dict[str, str]
    trace_path: str


def _json_load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _count_files(target: Path) -> int:
    if not target.exists():
        return 0
    return sum(1 for item in target.rglob("*") if item.is_file())


def _copy_case_tree(raw_case_dir: Path, final_case_dir: Path) -> None:
    if final_case_dir.exists():
        shutil.rmtree(final_case_dir)
    if raw_case_dir.exists():
        shutil.copytree(raw_case_dir, final_case_dir)
    else:
        final_case_dir.mkdir(parents=True, exist_ok=True)


def _normalize_case_result(case_def: dict[str, Any], final_case_dir: Path) -> CaseSummary:
    request_payload = _json_load(final_case_dir / "request.json", {})
    snapshot = _json_load(final_case_dir / "snapshot.json", {})
    artifacts = _json_load(final_case_dir / "artifacts.json", {})
    case_result = _json_load(final_case_dir / "case_result.json", {})
    final_report = snapshot.get("final_report") if isinstance(snapshot.get("final_report"), dict) else {}
    screenshots = case_result.get("screenshots") if isinstance(case_result.get("screenshots"), dict) else {}

    def as_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    def as_str(value: Any) -> str:
        return str(value or "").strip()

    def as_bool(value: Any) -> bool:
        return bool(value)

    artifact_dir = final_case_dir / "cowork_artifacts"
    copied_artifacts = as_int(case_result.get("copied_artifacts")) or _count_files(artifact_dir)
    gate_failures = case_result.get("gate_failures")
    if not isinstance(gate_failures, list):
        gate_failures = list(final_report.get("quality_gate_failures") or []) if isinstance(final_report, dict) else []

    status = as_str(case_result.get("status")) or as_str(snapshot.get("status")) or "unknown"
    completion_status = as_str(case_result.get("completion_status")) or as_str(final_report.get("completion_status"))
    qa_signoff = as_str(case_result.get("qa_signoff")) or as_str(final_report.get("qa_signoff"))
    execution_link = as_str(case_result.get("execution_link")) or as_str(final_report.get("execution_link"))
    entry_artifact_url = as_str(case_result.get("entry_artifact_url")) or as_str(final_report.get("entry_artifact_url"))
    project_profile = as_str(case_result.get("project_profile")) or as_str(final_report.get("project_profile"))
    planning_gate_status = as_str(case_result.get("planning_gate_status")) or as_str(final_report.get("planning_gate_status"))
    requested_case_timeout_sec = as_int(case_result.get("requested_case_timeout_sec"))
    applied_case_timeout_sec = as_int(case_result.get("applied_case_timeout_sec"))
    budget_floor_sec = as_int(case_result.get("budget_floor_sec")) or as_int(snapshot.get("budget_floor_sec"))
    budget_auto_raised = as_bool(case_result.get("budget_auto_raised")) or as_bool(snapshot.get("budget_auto_raised"))
    stop_reason = as_str(case_result.get("stop_reason")) or as_str(snapshot.get("stop_reason"))
    stop_source = as_str(case_result.get("stop_source")) or as_str(snapshot.get("stop_source"))
    timeout_event = snapshot.get("last_timeout_event") if isinstance(snapshot.get("last_timeout_event"), dict) else {}
    timeout_origin = as_str(case_result.get("timeout_origin")) or as_str(timeout_event.get("origin"))
    timeout_actor_label = as_str(case_result.get("timeout_actor_label")) or as_str(timeout_event.get("label"))
    timeout_actor_role = as_str(case_result.get("timeout_actor_role")) or as_str(timeout_event.get("role"))
    timeout_stage_type = as_str(case_result.get("timeout_stage_type")) or as_str(timeout_event.get("stage_type"))
    error_summary = as_str(case_result.get("error_summary"))
    if not error_summary:
        errors = snapshot.get("errors") if isinstance(snapshot.get("errors"), list) else []
        if errors:
            latest = errors[-1] if isinstance(errors[-1], dict) else {}
            error_summary = as_str(latest.get("error_text")) or as_str(latest.get("response_text"))

    for required_name in ("request.json", "snapshot.json", "artifacts.json", "status.log"):
        target = final_case_dir / required_name
        if not target.exists():
            if target.suffix == ".json":
                _write_json(target, {})
            else:
                _write_text(target, "")

    if not screenshots:
        screenshots = {
            "cowork_panel": "ui/cowork-panel.png" if (final_case_dir / "ui" / "cowork-panel.png").exists() else "",
            "project_page": "ui/project-page.png" if (final_case_dir / "ui" / "project-page.png").exists() else "",
            "failure_panel": "ui/failure-panel.png" if (final_case_dir / "ui" / "failure-panel.png").exists() else "",
        }

    trace_path = as_str(case_result.get("trace_path"))
    if not trace_path and (final_case_dir / "playwright" / "trace.zip").exists():
        trace_path = "playwright/trace.zip"

    tasks_count = as_int(case_result.get("tasks")) or len(snapshot.get("tasks") or [])
    stages_count = as_int(case_result.get("stages")) or len(snapshot.get("stages") or [])
    errors_count = as_int(case_result.get("errors")) or len(snapshot.get("errors") or [])

    if not isinstance(artifacts, dict):
        artifacts = {}
    if "root_dir" in artifacts and artifacts["root_dir"] is None:
        artifacts["root_dir"] = ""
    _write_json(final_case_dir / "artifacts.json", artifacts)
    _write_json(final_case_dir / "request.json", request_payload if isinstance(request_payload, dict) else {})
    _write_json(final_case_dir / "snapshot.json", snapshot if isinstance(snapshot, dict) else {})

    return CaseSummary(
        case_no=as_int(case_def.get("case_no")),
        case_id=as_str(case_def.get("case_id")),
        task=as_str(case_def.get("task")),
        expected_profile=as_str(case_def.get("expected_profile")),
        cowork_id=as_str(case_result.get("cowork_id")) or as_str(snapshot.get("cowork_id")),
        status=status,
        completion_status=completion_status,
        qa_signoff=qa_signoff,
        execution_link=execution_link,
        entry_artifact_url=entry_artifact_url,
        project_profile=project_profile,
        planning_gate_status=planning_gate_status,
        tasks=tasks_count,
        stages=stages_count,
        errors=errors_count,
        copied_artifacts=copied_artifacts,
        timed_out=as_bool(case_result.get("timed_out")),
        requested_case_timeout_sec=requested_case_timeout_sec,
        applied_case_timeout_sec=applied_case_timeout_sec,
        budget_floor_sec=budget_floor_sec,
        budget_auto_raised=budget_auto_raised,
        stop_reason=stop_reason,
        stop_source=stop_source,
        timeout_origin=timeout_origin,
        timeout_actor_label=timeout_actor_label,
        timeout_actor_role=timeout_actor_role,
        timeout_stage_type=timeout_stage_type,
        error_summary=error_summary,
        gate_failures=[str(item) for item in gate_failures],
        screenshots={key: as_str(value) for key, value in screenshots.items()},
        trace_path=trace_path,
    )


def _write_case_summary(case_dir: Path, summary: CaseSummary) -> None:
    lines = [
        f"# {summary.case_id}",
        "",
        f"- task: `{summary.task}`",
        f"- expected_profile: `{summary.expected_profile}`",
        f"- status: `{summary.status}`",
        f"- completion_status: `{summary.completion_status or '-'}`",
        f"- qa_signoff: `{summary.qa_signoff or '-'}`",
        f"- project_profile: `{summary.project_profile or '-'}`",
        f"- planning_gate: `{summary.planning_gate_status or '-'}`",
        f"- cowork_id: `{summary.cowork_id or '-'}`",
        f"- execution_link: `{summary.execution_link or '-'}`",
        f"- entry_artifact_url: `{summary.entry_artifact_url or '-'}`",
        f"- tasks: `{summary.tasks}`",
        f"- stages: `{summary.stages}`",
        f"- errors: `{summary.errors}`",
        f"- copied_artifacts: `{summary.copied_artifacts}`",
        f"- timed_out: `{summary.timed_out}`",
        f"- requested_case_timeout_sec: `{summary.requested_case_timeout_sec}`",
        f"- applied_case_timeout_sec: `{summary.applied_case_timeout_sec}`",
        f"- budget_floor_sec: `{summary.budget_floor_sec}`",
        f"- budget_auto_raised: `{summary.budget_auto_raised}`",
        f"- stop_reason: `{summary.stop_reason or '-'}`",
        f"- stop_source: `{summary.stop_source or '-'}`",
        f"- timeout_origin: `{summary.timeout_origin or '-'}`",
        f"- timeout_actor: `{summary.timeout_actor_label or '-'}` / `{summary.timeout_actor_role or '-'}` / `{summary.timeout_stage_type or '-'}`",
        f"- error_summary: `{summary.error_summary or '-'}`",
        "",
        "## Evidence",
        "",
    ]
    if summary.screenshots.get("cowork_panel"):
        lines.append(f"- cowork panel: [{summary.screenshots['cowork_panel']}]({summary.screenshots['cowork_panel']})")
    if summary.screenshots.get("project_page"):
        lines.append(f"- project page: [{summary.screenshots['project_page']}]({summary.screenshots['project_page']})")
    if summary.screenshots.get("failure_panel"):
        lines.append(f"- failure panel: [{summary.screenshots['failure_panel']}]({summary.screenshots['failure_panel']})")
    if summary.trace_path:
        lines.append(f"- trace: [{summary.trace_path}]({summary.trace_path})")
    if summary.gate_failures:
        lines.extend(["", "## Gate Failures", ""])
        for item in summary.gate_failures:
            lines.append(f"- {item}")
    _write_text(case_dir / "summary.md", "\n".join(lines).strip() + "\n")


def _build_report_markdown(
    suite_dir: Path,
    base_url: str,
    headed: bool,
    ports: dict[str, int | None],
    selected_bots: list[str],
    results: list[CaseSummary],
    summary: dict[str, int],
) -> str:
    lines = [
        "# Cowork Web 10 Cases Live Rerun Report",
        "",
        f"- suite_dir: {suite_dir}",
        f"- base: {base_url}",
        f"- headed: {headed}",
        f"- total: {summary['total']}",
        f"- completed: {summary['completed']}",
        f"- passed: {summary['passed']}",
        f"- failed: {summary['failed']}",
        f"- stopped: {summary['stopped']}",
        f"- timed_out: {summary['timed_out']}",
        f"- other: {summary['other']}",
        "",
        "| # | status | completion | qa_signoff | profile | planning_gate | tasks | errors | timed_out | timeout_origin | cowork_id |",
        "|---|---|---|---|---|---|---:|---:|---|---|---|",
    ]
    for row in results:
        lines.append(
            f"| {row.case_no:02d} | {row.status} | {row.completion_status or '-'} | {row.qa_signoff or '-'} | {row.project_profile or row.expected_profile or '-'} | {row.planning_gate_status or '-'} | {row.tasks} | {row.errors} | {row.timed_out} | {row.timeout_origin or '-'} | {row.cowork_id or '-'} |"
        )

    lines.extend(
        [
            "",
            "## Execution Environment",
            "",
            f"- base URL: `{base_url}`",
            f"- mode: `{'headed' if headed else 'headless'}`",
            f"- temp ports: `mock={ports.get('mock_port')}` `embedded_base={ports.get('embedded_base_port')}` `gateway={ports.get('gateway_port')}`",
            f"- selected bots: `{', '.join(selected_bots)}`",
            "",
            "## Failure Cases",
            "",
        ]
    )
    failures = [row for row in results if row.status != 'completed' or row.completion_status not in {'passed', 'PASS'}]
    if not failures:
        lines.append("- none")
    else:
        for row in failures:
            lines.append(
                f"- `{row.case_id}`: status={row.status}, completion={row.completion_status or '-'}, "
                f"timeout_origin={row.timeout_origin or '-'}, stop={row.stop_source or '-'}:{row.stop_reason or '-'}, error={row.error_summary or '-'}"
            )

    lines.extend(["", "## Case Links", ""])
    for row in results:
        case_prefix = row.case_id
        lines.append(f"- `{case_prefix}`: [summary](./{case_prefix}/summary.md)")
        if row.screenshots.get('cowork_panel'):
            lines.append(f"  cowork: `./{case_prefix}/{row.screenshots['cowork_panel']}`")
        if row.screenshots.get('project_page'):
            lines.append(f"  project: `./{case_prefix}/{row.screenshots['project_page']}`")
        controller_report = suite_dir / case_prefix / 'cowork_artifacts' / 'final' / 'controller_final_report.md'
        if controller_report.exists():
            lines.append(f"  controller_report: `./{case_prefix}/cowork_artifacts/final/controller_final_report.md`")
    return "\n".join(lines).strip() + "\n"


def _summaries(rows: list[CaseSummary]) -> dict[str, int]:
    summary = {
        "total": len(rows),
        "completed": 0,
        "passed": 0,
        "failed": 0,
        "stopped": 0,
        "timed_out": 0,
        "other": 0,
    }
    for row in rows:
        if row.status == "completed":
            summary["completed"] += 1
        elif row.status in {"failed", "infra_failed"}:
            summary["failed"] += 1
        elif row.status == "stopped":
            summary["stopped"] += 1
        else:
            summary["other"] += 1
        if row.completion_status.lower() == "passed":
            summary["passed"] += 1
        if row.timed_out:
            summary["timed_out"] += 1
    return summary


def build_suite_report(args: argparse.Namespace) -> dict[str, Any]:
    suite_dir = Path(args.suite_dir).expanduser().resolve()
    raw_dir = Path(args.raw_dir).expanduser().resolve()
    fixture_path = Path(args.fixture_path).expanduser().resolve()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    suite_dir.mkdir(parents=True, exist_ok=True)

    results: list[CaseSummary] = []
    for case_def in fixture:
        case_id = str(case_def.get("case_id") or "").strip()
        raw_case_dir = raw_dir / case_id
        final_case_dir = suite_dir / case_id
        _copy_case_tree(raw_case_dir, final_case_dir)
        summary = _normalize_case_result(case_def, final_case_dir)
        _write_case_summary(final_case_dir, summary)
        results.append(summary)

    results.sort(key=lambda item: item.case_no)
    summary_counts = _summaries(results)
    report = {
        "base": args.base_url,
        "suite_dir": str(suite_dir),
        "headed": bool(args.headed),
        "max_turn_sec": int(args.max_turn_sec),
        "case_timeout_sec": int(args.case_timeout_sec),
        "started_at": args.started_at,
        "finished_at": args.finished_at,
        "results": [
            {
                "case_no": row.case_no,
                "case_id": row.case_id,
                "task": row.task,
                "expected_profile": row.expected_profile,
                "cowork_id": row.cowork_id,
                "status": row.status,
                "completion_status": row.completion_status,
                "qa_signoff": row.qa_signoff,
                "execution_link": row.execution_link,
                "entry_artifact_url": row.entry_artifact_url,
                "project_profile": row.project_profile,
                "planning_gate_status": row.planning_gate_status,
                "tasks": row.tasks,
                "stages": row.stages,
                "errors": row.errors,
                "copied_artifacts": row.copied_artifacts,
                "timed_out": row.timed_out,
                "requested_case_timeout_sec": row.requested_case_timeout_sec,
                "applied_case_timeout_sec": row.applied_case_timeout_sec,
                "budget_floor_sec": row.budget_floor_sec,
                "budget_auto_raised": row.budget_auto_raised,
                "stop_reason": row.stop_reason,
                "stop_source": row.stop_source,
                "timeout_origin": row.timeout_origin,
                "timeout_actor_label": row.timeout_actor_label,
                "timeout_actor_role": row.timeout_actor_role,
                "timeout_stage_type": row.timeout_stage_type,
                "error_summary": row.error_summary,
                "gate_failures": row.gate_failures,
                "screenshots": row.screenshots,
                "trace_path": row.trace_path,
            }
            for row in results
        ],
        "summary": summary_counts,
    }
    suite_meta = {
        "suite_dir": str(suite_dir),
        "raw_dir": str(raw_dir),
        "fixture_path": str(fixture_path),
        "base_url": args.base_url,
        "headed": bool(args.headed),
        "max_turn_sec": int(args.max_turn_sec),
        "case_timeout_sec": int(args.case_timeout_sec),
        "ports": {
            "mock_port": args.mock_port,
            "embedded_base_port": args.embedded_base_port,
            "gateway_port": args.gateway_port,
        },
        "selected_bots": args.selected_bots,
        "started_at": args.started_at,
        "finished_at": args.finished_at,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(suite_dir / "suite_meta.json", suite_meta)
    _write_json(suite_dir / "report.json", report)
    _write_text(
        suite_dir / "report.md",
        _build_report_markdown(
            suite_dir=suite_dir,
            base_url=args.base_url,
            headed=bool(args.headed),
            ports={
                "mock_port": args.mock_port,
                "embedded_base_port": args.embedded_base_port,
                "gateway_port": args.gateway_port,
            },
            selected_bots=args.selected_bots,
            results=results,
            summary=summary_counts,
        ),
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate live cowork web suite raw outputs into result reports.")
    parser.add_argument("--suite-dir", required=True)
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--fixture-path", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--max-turn-sec", type=int, required=True)
    parser.add_argument("--case-timeout-sec", type=int, required=True)
    parser.add_argument("--mock-port", type=int, required=True)
    parser.add_argument("--embedded-base-port", type=int, required=True)
    parser.add_argument("--gateway-port", type=int, required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--finished-at", required=True)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--selected-bots", nargs="*", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_suite_report(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
