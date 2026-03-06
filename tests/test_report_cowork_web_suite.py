from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path


def _load_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("report_cowork_web_suite", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_suite_report_generates_expected_files(tmp_path: Path) -> None:
    script_path = Path.cwd() / "scripts" / "report_cowork_web_suite.py"
    module = _load_module(script_path)

    suite_dir = tmp_path / "result-suite"
    raw_dir = suite_dir / ".raw"
    case_id = "01_mvp-hero-benefits-cta-index-html-styles-css"
    raw_case_dir = raw_dir / case_id
    (raw_case_dir / "ui").mkdir(parents=True, exist_ok=True)
    (raw_case_dir / "playwright").mkdir(parents=True, exist_ok=True)
    (raw_case_dir / "cowork_artifacts" / "final").mkdir(parents=True, exist_ok=True)
    (raw_case_dir / "ui" / "cowork-panel.png").write_bytes(b"png")
    (raw_case_dir / "ui" / "project-page.png").write_bytes(b"png")
    (raw_case_dir / "cowork_artifacts" / "final" / "controller_final_report.md").write_text("ok", encoding="utf-8")

    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            [
                {
                    "case_no": 1,
                    "case_id": case_id,
                    "task": "랜딩 페이지 MVP 구현",
                    "project_id": "web-cowork-r3-01-landing-page-mvp",
                    "expected_profile": "landing-basic",
                    "max_parallel": 3,
                    "max_turn_sec": 45,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (raw_case_dir / "request.json").write_text(
        json.dumps({"command_text": "/cowork ...", "case_def": {"case_id": case_id}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (raw_case_dir / "snapshot.json").write_text(
        json.dumps(
            {
                "cowork_id": "cowork-001",
                "status": "completed",
                "tasks": [{"task_no": 1}],
                "stages": [{"stage_no": 1}],
                "errors": [],
                "final_report": {
                    "completion_status": "passed",
                    "qa_signoff": "APPROVED",
                    "execution_link": "/_mock/cowork/cowork-001/artifact/index.html",
                    "entry_artifact_url": "/_mock/cowork/cowork-001/artifact/index.html",
                    "project_profile": "landing-basic",
                    "planning_gate_status": "fallback",
                    "quality_gate_failures": [],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (raw_case_dir / "artifacts.json").write_text(
        json.dumps(
            {
                "root_dir": str(raw_case_dir / "cowork_artifacts"),
                "files": [
                    {
                        "name": "final/controller_final_report.md",
                        "path": str(raw_case_dir / "cowork_artifacts" / "final" / "controller_final_report.md"),
                        "url": "/_mock/cowork/cowork-001/artifact/final/controller_final_report.md",
                        "size_bytes": 2,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (raw_case_dir / "status.log").write_text("[2026-03-06T00:00:00Z] started\n", encoding="utf-8")
    (raw_case_dir / "case_result.json").write_text(
        json.dumps(
            {
                "case_no": 1,
                "case_id": case_id,
                "task": "랜딩 페이지 MVP 구현",
                "expected_profile": "landing-basic",
                "cowork_id": "cowork-001",
                "status": "completed",
                "completion_status": "passed",
                "qa_signoff": "APPROVED",
                "execution_link": "/_mock/cowork/cowork-001/artifact/index.html",
                "entry_artifact_url": "/_mock/cowork/cowork-001/artifact/index.html",
                "project_profile": "landing-basic",
                "planning_gate_status": "fallback",
                "tasks": 1,
                "stages": 1,
                "errors": 0,
                "copied_artifacts": 1,
                "timed_out": False,
                "error_summary": "",
                "gate_failures": [],
                "screenshots": {
                    "cowork_panel": "ui/cowork-panel.png",
                    "project_page": "ui/project-page.png",
                    "failure_panel": "",
                },
                "trace_path": "",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    report = module.build_suite_report(
        Namespace(
            suite_dir=str(suite_dir),
            raw_dir=str(raw_dir),
            fixture_path=str(fixture_path),
            base_url="http://127.0.0.1:9182",
            headed=True,
            max_turn_sec=45,
            case_timeout_sec=240,
            mock_port=9182,
            embedded_base_port=8700,
            gateway_port=4412,
            selected_bots=["bot-a", "bot-b", "bot-c", "bot-d", "bot-e"],
            started_at="2026-03-06T00:00:00Z",
            finished_at="2026-03-06T00:10:00Z",
        )
    )

    assert report["summary"]["total"] == 1
    assert report["summary"]["completed"] == 1
    assert report["summary"]["passed"] == 1
    assert report["results"][0]["entry_artifact_url"] == "/_mock/cowork/cowork-001/artifact/index.html"
    assert (suite_dir / "report.json").exists()
    assert (suite_dir / "report.md").exists()
    assert (suite_dir / "suite_meta.json").exists()
    assert (suite_dir / case_id / "summary.md").exists()
    assert "landing-basic" in (suite_dir / "report.md").read_text(encoding="utf-8")
