const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');
const {
  appendStatusLine,
  captureCoworkEvidence,
  clearActiveCowork,
  copyArtifactTree,
  ensureDir,
  ensureTargetBots,
  fetchCoworkArtifacts,
  fetchCoworkSnapshot,
  resolveCaseTimeout,
  setBotRole,
  startCoworkViaUi,
  waitCoworkTerminal,
  writeCaseRawFiles,
} = require('../helpers/cowork_live_suite');

const FIXTURE_PATH = path.resolve(__dirname, '..', 'fixtures', 'cowork_web_10cases.json');
const ROLE_MAP = [
  ['bot-a', 'planner'],
  ['bot-b', 'controller'],
  ['bot-c', 'implementer'],
  ['bot-d', 'qa'],
  ['bot-e', 'implementer'],
];

function loadCaseDefinition() {
  const caseNo = Number(process.env.COWORK_LIVE_CASE_NO || '0');
  if (!Number.isFinite(caseNo) || caseNo < 1) {
    throw new Error('COWORK_LIVE_CASE_NO is required');
  }
  const rows = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf-8'));
  const match = rows.find((row) => Number(row.case_no) === caseNo);
  if (!match) {
    throw new Error(`fixture case not found: ${caseNo}`);
  }
  return match;
}

function terminalStatus(status) {
  const text = String(status || '').trim().toLowerCase();
  return ['completed', 'failed', 'stopped'].includes(text);
}

function summarizeError(snapshot, timedOut, fallback = '') {
  if (timedOut) {
    return 'case timeout';
  }
  const errors = Array.isArray(snapshot?.errors) ? snapshot.errors : [];
  const latest = errors[errors.length - 1] || null;
  const latestText = String(latest?.error_text || latest?.response_text || '').trim();
  if (latestText) {
    return latestText;
  }
  const finalReport = snapshot?.final_report && typeof snapshot.final_report === 'object' ? snapshot.final_report : null;
  const gateFailures = Array.isArray(finalReport?.quality_gate_failures) ? finalReport.quality_gate_failures : [];
  if (gateFailures.length > 0) {
    return gateFailures.join('; ');
  }
  return String(fallback || '').trim();
}

function countRows(snapshot, key) {
  return Array.isArray(snapshot?.[key]) ? snapshot[key].length : 0;
}

test('live cowork ui case runner', async ({ page, request, context }) => {
  const caseDef = loadCaseDefinition();
  const baseURL = process.env.MOCK_UI_BASE_URL || 'http://127.0.0.1:9082';
  const rawRoot = path.resolve(process.env.COWORK_LIVE_RAW_DIR || 'output/playwright/cowork-live-raw');
  const caseTimeoutSec = Math.max(30, Number(process.env.COWORK_CASE_TIMEOUT_SEC || '240'));
  const allowUnsafeTimeout = String(process.env.COWORK_ALLOW_UNSAFE_TIMEOUT || '').trim().toLowerCase() === '1';
  const caseDir = path.join(rawRoot, caseDef.case_id);
  const statusLines = [];
  const startedAt = new Date().toISOString();
  let traceStopped = false;
  let requestPayload = {
    case_def: caseDef,
    command_text: '',
    request_payload: null,
    response_status: 0,
    response_payload: null,
  };
  let snapshot = null;
  let artifacts = null;
  let screenshots = {
    cowork_panel: '',
    project_page: '',
    failure_panel: '',
  };
  let tracePath = '';

  test.setTimeout((caseTimeoutSec + 90) * 1000);
  fs.rmSync(caseDir, { recursive: true, force: true });
  ensureDir(caseDir);
  ensureDir(path.join(caseDir, 'ui'));
  ensureDir(path.join(caseDir, 'playwright'));

  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });

  try {
    appendStatusLine(statusLines, `case start: ${caseDef.case_id}`);
    page.setDefaultTimeout(30000);
    await page.goto('/_mock/ui', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await expect(page.locator('#bot-list')).toBeVisible();
    await ensureTargetBots(page, request, ROLE_MAP.map(([botId]) => botId), statusLines);

    for (const [botId, role] of ROLE_MAP) {
      await setBotRole(page, request, botId, role, statusLines);
    }

    await clearActiveCowork(request, statusLines);

    const commandText = `/cowork ${caseDef.task} --project-id ${caseDef.project_id} --max-parallel ${caseDef.max_parallel} --max-turn-sec ${caseDef.max_turn_sec}`;
    requestPayload = {
      case_def: caseDef,
      ...(await startCoworkViaUi(page, commandText, statusLines)),
    };

    const coworkId = String(requestPayload?.response_payload?.result?.cowork_id || '').trim();
    if (!coworkId) {
      throw new Error(`cowork start response missing cowork_id for ${caseDef.case_id}`);
    }
    appendStatusLine(statusLines, `cowork id: ${coworkId}`);

    const timeoutBudget = resolveCaseTimeout(
      requestPayload?.response_payload?.result || null,
      caseTimeoutSec,
      allowUnsafeTimeout,
      statusLines
    );

    let terminal = await waitCoworkTerminal(page, request, coworkId, timeoutBudget.applied_case_timeout_sec, statusLines);
    snapshot = terminal?.snapshot || null;

    if (terminal?.timed_out) {
      appendStatusLine(statusLines, `timeout stop requested for ${coworkId}`);
      try {
        await request.post(`/_mock/cowork/${encodeURIComponent(coworkId)}/stop`, {
          data: {
            reason: 'case_timeout',
            source: 'cowork-web-live-suite',
            requested_by: 'playwright',
          },
        });
      } catch (error) {
        appendStatusLine(statusLines, `timeout stop request failed: ${error.message}`);
      }
      await page.waitForTimeout(2000);
      snapshot = await fetchCoworkSnapshot(request, baseURL, coworkId).catch(() => snapshot);
    } else if (!snapshot || !terminalStatus(snapshot?.status)) {
      snapshot = await fetchCoworkSnapshot(request, baseURL, coworkId).catch(() => snapshot);
    }

    artifacts = await fetchCoworkArtifacts(request, baseURL, coworkId);
    const copiedArtifacts = copyArtifactTree(artifacts, caseDir);
    screenshots = await captureCoworkEvidence(page, baseURL, caseDir, snapshot || {}, { timedOut: Boolean(terminal?.timed_out) });

    const finalReport = snapshot?.final_report && typeof snapshot.final_report === 'object' ? snapshot.final_report : {};
    const caseResult = {
      case_no: Number(caseDef.case_no),
      case_id: String(caseDef.case_id),
      task: String(caseDef.task),
      expected_profile: String(caseDef.expected_profile),
      project_id: String(caseDef.project_id),
      cowork_id: String(snapshot?.cowork_id || coworkId),
      status: String(snapshot?.status || (terminal?.timed_out ? 'timed_out' : 'unknown')),
      completion_status: String(finalReport.completion_status || ''),
      qa_signoff: String(finalReport.qa_signoff || ''),
      execution_link: String(finalReport.execution_link || ''),
      entry_artifact_url: String(finalReport.entry_artifact_url || ''),
      project_profile: String(finalReport.project_profile || ''),
      planning_gate_status: String(finalReport.planning_gate_status || ''),
      tasks: countRows(snapshot, 'tasks'),
      stages: countRows(snapshot, 'stages'),
      errors: countRows(snapshot, 'errors'),
      copied_artifacts: copiedArtifacts,
      timed_out: Boolean(terminal?.timed_out),
      requested_case_timeout_sec: timeoutBudget.requested_case_timeout_sec,
      applied_case_timeout_sec: timeoutBudget.applied_case_timeout_sec,
      budget_floor_sec: timeoutBudget.budget_floor_sec,
      budget_auto_raised: timeoutBudget.budget_auto_raised,
      stop_reason: String(snapshot?.stop_reason || ''),
      stop_source: String(snapshot?.stop_source || ''),
      timeout_origin: String(snapshot?.last_timeout_event?.origin || ''),
      timeout_actor_label: String(snapshot?.last_timeout_event?.label || ''),
      timeout_actor_role: String(snapshot?.last_timeout_event?.role || ''),
      timeout_stage_type: String(snapshot?.last_timeout_event?.stage_type || ''),
      error_summary: summarizeError(snapshot, Boolean(terminal?.timed_out)),
      gate_failures: Array.isArray(finalReport.quality_gate_failures) ? finalReport.quality_gate_failures : [],
      screenshots,
      trace_path: '',
      started_at: startedAt,
      finished_at: new Date().toISOString(),
    };

    if (caseResult.timed_out || ['failed', 'stopped'].includes(caseResult.status) || caseResult.completion_status === 'needs_rework') {
      tracePath = path.join('playwright', 'trace.zip');
      await context.tracing.stop({ path: path.join(caseDir, tracePath) });
      traceStopped = true;
      caseResult.trace_path = tracePath;
    } else {
      await context.tracing.stop();
      traceStopped = true;
    }

    writeCaseRawFiles(caseDir, {
      request: requestPayload,
      snapshot: snapshot || {},
      artifacts: artifacts || {},
      status_lines: statusLines,
      case_result: caseResult,
    });
  } catch (error) {
    appendStatusLine(statusLines, `infra error: ${error.message}`);
    try {
      const failurePath = path.join(caseDir, 'ui', 'failure-panel.png');
      await page.screenshot({ path: failurePath, fullPage: true });
      screenshots.failure_panel = path.join('ui', 'failure-panel.png');
    } catch {
      // ignore secondary screenshot failures
    }

    if (!traceStopped) {
      tracePath = path.join('playwright', 'trace.zip');
      try {
        await context.tracing.stop({ path: path.join(caseDir, tracePath) });
      } catch {
        // ignore secondary trace failures
      }
      traceStopped = true;
    }

    writeCaseRawFiles(caseDir, {
      request: requestPayload,
      snapshot: snapshot || {},
      artifacts: artifacts || {},
      status_lines: statusLines,
      case_result: {
        case_no: Number(caseDef.case_no),
        case_id: String(caseDef.case_id),
        task: String(caseDef.task),
        expected_profile: String(caseDef.expected_profile),
        project_id: String(caseDef.project_id),
        cowork_id: String(snapshot?.cowork_id || ''),
        status: 'infra_failed',
        completion_status: '',
        qa_signoff: '',
        execution_link: '',
        entry_artifact_url: '',
        project_profile: '',
        planning_gate_status: '',
        tasks: countRows(snapshot, 'tasks'),
        stages: countRows(snapshot, 'stages'),
        errors: countRows(snapshot, 'errors'),
        copied_artifacts: 0,
        timed_out: false,
        error_summary: String(error.message || error),
        gate_failures: [],
        screenshots,
        trace_path: tracePath,
        started_at: startedAt,
        finished_at: new Date().toISOString(),
      },
      error_text: String(error.stack || error.message || error),
    });
    throw error;
  } finally {
    if (!traceStopped) {
      try {
        await context.tracing.stop();
      } catch {
        // ignore final trace cleanup failures
      }
    }
  }
});
