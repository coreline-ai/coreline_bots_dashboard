from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tests" / "e2e" / "helpers" / "cowork_live_suite.js"


def _run_node(script: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for cowork live suite helper tests")
    completed = subprocess.run(
        [node, "-e", script],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip())


def test_resolve_case_timeout_auto_raises_to_budget_floor_plus_margin() -> None:
    payload = _run_node(
        f"""
const helper = require({json.dumps(str(HELPER))});
const result = helper.resolveCaseTimeout({{ budget_floor_sec: 180 }}, 120, false, []);
console.log(JSON.stringify(result));
"""
    )
    assert payload["requested_case_timeout_sec"] == 120
    assert payload["applied_case_timeout_sec"] == 200
    assert payload["budget_floor_sec"] == 180
    assert payload["budget_auto_raised"] is True


def test_resolve_case_timeout_keeps_requested_value_when_unsafe_is_allowed() -> None:
    payload = _run_node(
        f"""
const helper = require({json.dumps(str(HELPER))});
const result = helper.resolveCaseTimeout({{ budget_floor_sec: 180 }}, 120, true, []);
console.log(JSON.stringify(result));
"""
    )
    assert payload["requested_case_timeout_sec"] == 120
    assert payload["applied_case_timeout_sec"] == 120
    assert payload["budget_floor_sec"] == 180
    assert payload["budget_auto_raised"] is False
