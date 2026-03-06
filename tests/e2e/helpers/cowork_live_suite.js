const fs = require('fs');
const path = require('path');

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function writeJson(filePath, payload) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), 'utf-8');
}

function writeText(filePath, content) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, content, 'utf-8');
}

function isoNow() {
  return new Date().toISOString();
}

function appendStatusLine(statusLines, text) {
  statusLines.push(`[${isoNow()}] ${text}`);
}

function resolveAbsoluteUrl(baseURL, rawUrl) {
  const text = String(rawUrl || '').trim();
  if (!text) {
    return '';
  }
  return new URL(text, baseURL).toString();
}

async function getJson(request, urlPath) {
  const response = await request.get(urlPath);
  if (!response.ok()) {
    const body = await response.text().catch(() => '');
    throw new Error(`request failed ${response.status()} ${urlPath}: ${body}`);
  }
  return await response.json();
}

async function postJson(request, urlPath, data) {
  const response = await request.post(urlPath, { data });
  if (!response.ok()) {
    const body = await response.text().catch(() => '');
    throw new Error(`request failed ${response.status()} ${urlPath}: ${body}`);
  }
  return await response.json();
}

async function fetchCatalog(request) {
  const payload = await getJson(request, '/_mock/bot_catalog');
  const bots = Array.isArray(payload?.result?.bots) ? payload.result.bots : [];
  return bots;
}

async function botIndexById(request, botId) {
  const bots = await fetchCatalog(request);
  return bots.findIndex((row) => String(row?.bot_id || '') === String(botId || ''));
}

async function clickBotCard(page, request, botId) {
  const index = await botIndexById(request, botId);
  if (index < 0) {
    throw new Error(`bot not found in catalog: ${botId}`);
  }
  const cards = page.locator('.bot-item');
  await cards.nth(index).click();
  await page.waitForFunction(
    (expectedBotId) => {
      const input = document.getElementById('bot-id-input');
      return input && input.value === expectedBotId;
    },
    botId,
    { timeout: 10000 }
  );
  return index;
}

async function ensureTargetBots(page, request, botIds, statusLines = []) {
  const expectedIds = Array.isArray(botIds) ? botIds.map((value) => String(value)) : [];
  const bots = await fetchCatalog(request);
  const actualIds = bots.map((row) => String(row?.bot_id || ''));
  for (const botId of expectedIds) {
    if (!actualIds.includes(botId)) {
      throw new Error(`required bot missing from catalog: ${botId}`);
    }
  }
  await page.locator('#bot-list .bot-item').first().waitFor({ state: 'visible', timeout: 15000 });
  for (let index = 0; index < bots.length; index += 1) {
    const botId = String(bots[index]?.bot_id || '');
    const shouldSelect = expectedIds.includes(botId);
    const checkbox = page.locator('.bot-item').nth(index).locator('.bot-item-check');
    if ((await checkbox.isChecked()) !== shouldSelect) {
      await checkbox.setChecked(shouldSelect);
    }
  }
  if (expectedIds.length > 0) {
    await clickBotCard(page, request, expectedIds[0]);
  }
  appendStatusLine(statusLines, `parallel target bots ready: ${expectedIds.join(', ')}`);
}

async function setBotRole(page, request, botId, role, statusLines = []) {
  await clickBotCard(page, request, botId);
  const roleSelect = page.locator('#session-role-select');
  await roleSelect.waitFor({ state: 'visible', timeout: 10000 });
  const nextRole = String(role || 'implementer');
  const currentRole = await roleSelect.inputValue();
  if (currentRole === nextRole) {
    appendStatusLine(statusLines, `role already set: ${botId} -> ${role}`);
    return;
  }
  await Promise.all([
    page.waitForResponse((response) => response.url().includes('/_mock/bot_catalog/role') && response.request().method() === 'POST', { timeout: 10000 }),
    roleSelect.selectOption(nextRole),
  ]);
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const bots = await fetchCatalog(request);
    const row = bots.find((item) => String(item?.bot_id || '') === String(botId || '')) || null;
    if (row && String(row.default_role || '') === String(role || '')) {
      appendStatusLine(statusLines, `role applied: ${botId} -> ${role}`);
      return;
    }
    await page.waitForTimeout(300);
  }
  throw new Error(`role application not reflected in catalog: ${botId} -> ${role}`);
}

async function clearActiveCowork(request, statusLines = []) {
  const payload = await getJson(request, '/_mock/cowork/active');
  const active = payload?.result || null;
  const coworkId = String(active?.cowork_id || '').trim();
  if (!coworkId) {
    appendStatusLine(statusLines, 'no active cowork to clear');
    return null;
  }
  appendStatusLine(statusLines, `active cowork detected: ${coworkId}`);
  await postJson(request, `/_mock/cowork/${encodeURIComponent(coworkId)}/stop`, {
    reason: 'runner_cleanup',
    source: 'cowork-web-live-suite',
    requested_by: 'playwright',
  });
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const response = await getJson(request, `/_mock/cowork/${encodeURIComponent(coworkId)}`);
    const snapshot = response?.result || null;
    const status = String(snapshot?.status || '').trim();
    if (['completed', 'failed', 'stopped'].includes(status)) {
      appendStatusLine(statusLines, `active cowork cleared: ${coworkId} -> ${status}`);
      return snapshot;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`timed out clearing active cowork: ${coworkId}`);
}

async function startCoworkViaUi(page, commandText, statusLines = []) {
  const input = page.locator('#parallel-message-input');
  const sendButton = page.locator('#parallel-send-btn');
  await input.waitFor({ state: 'visible', timeout: 10000 });
  await input.fill(String(commandText || ''));
  const requestPromise = page.waitForRequest(
    (request) => request.url().includes('/_mock/cowork/start') && request.method() === 'POST',
    { timeout: 15000 }
  );
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes('/_mock/cowork/start') && response.request().method() === 'POST',
    { timeout: 15000 }
  );
  await sendButton.click();
  const outboundRequest = await requestPromise;
  const inboundResponse = await responsePromise;
  let responsePayload = null;
  try {
    responsePayload = await inboundResponse.json();
  } catch {
    responsePayload = { ok: false, parse_error: true };
  }
  appendStatusLine(statusLines, `cowork start requested via UI: ${commandText}`);
  return {
    command_text: String(commandText || ''),
    request_payload: outboundRequest.postDataJSON() || null,
    response_status: inboundResponse.status(),
    response_payload: responsePayload,
  };
}

async function waitCoworkTerminal(page, request, coworkId, caseTimeoutSec, statusLines = []) {
  const deadline = Date.now() + Math.max(10, Number(caseTimeoutSec || 240)) * 1000;
  let lastSnapshot = null;
  let lastStatus = '';
  while (Date.now() < deadline) {
    const payload = await getJson(request, `/_mock/cowork/${encodeURIComponent(coworkId)}`);
    const snapshot = payload?.result || null;
    if (snapshot) {
      lastSnapshot = snapshot;
      const status = String(snapshot.status || 'unknown');
      if (status !== lastStatus) {
        lastStatus = status;
        appendStatusLine(statusLines, `cowork status: ${status}`);
      }
      if (['completed', 'failed', 'stopped'].includes(status)) {
        await page.waitForFunction(
          (expectedCoworkId) => {
            const meta = document.getElementById('cowork-meta');
            return meta && meta.textContent.includes(expectedCoworkId);
          },
          coworkId,
          { timeout: 10000 }
        ).catch(() => {});
        return { snapshot, timed_out: false };
      }
    }
    await page.waitForTimeout(1000);
  }
  appendStatusLine(statusLines, `cowork timeout reached after ${caseTimeoutSec}s`);
  return { snapshot: lastSnapshot, timed_out: true };
}

function resolveCaseTimeout(snapshot, requestedCaseTimeoutSec, allowUnsafeTimeout = false, statusLines = []) {
  const requested = Math.max(30, Number(requestedCaseTimeoutSec || 240));
  const budgetFloor = Math.max(0, Number(snapshot?.budget_floor_sec || 0));
  const safetyMarginSec = 20;
  let applied = requested;
  let autoRaised = false;
  if (!allowUnsafeTimeout && budgetFloor > 0 && requested < budgetFloor) {
    applied = budgetFloor + safetyMarginSec;
    autoRaised = true;
  }
  appendStatusLine(
    statusLines,
    `case timeout budget: requested=${requested}s floor=${budgetFloor || '-'}s applied=${applied}s auto_raised=${autoRaised}`
  );
  return {
    requested_case_timeout_sec: requested,
    applied_case_timeout_sec: applied,
    budget_floor_sec: budgetFloor || 0,
    budget_auto_raised: autoRaised,
  };
}

async function fetchCoworkSnapshot(request, baseURL, coworkId) {
  void baseURL;
  const payload = await getJson(request, `/_mock/cowork/${encodeURIComponent(coworkId)}`);
  return payload?.result || null;
}

async function fetchCoworkArtifacts(request, baseURL, coworkId) {
  void baseURL;
  try {
    const payload = await getJson(request, `/_mock/cowork/${encodeURIComponent(coworkId)}/artifacts`);
    return payload?.result || null;
  } catch {
    return null;
  }
}

function countFilesRecursive(targetDir) {
  if (!fs.existsSync(targetDir)) {
    return 0;
  }
  const entries = fs.readdirSync(targetDir, { withFileTypes: true });
  let total = 0;
  for (const entry of entries) {
    const nextPath = path.join(targetDir, entry.name);
    if (entry.isDirectory()) {
      total += countFilesRecursive(nextPath);
    } else if (entry.isFile()) {
      total += 1;
    }
  }
  return total;
}

function copyArtifactTree(artifactsPayload, caseDir) {
  const rootDir = String(artifactsPayload?.root_dir || '').trim();
  if (!rootDir || !fs.existsSync(rootDir)) {
    return 0;
  }
  const destDir = path.join(caseDir, 'cowork_artifacts');
  fs.rmSync(destDir, { recursive: true, force: true });
  fs.cpSync(rootDir, destDir, { recursive: true });
  return countFilesRecursive(destDir);
}

async function captureCoworkEvidence(page, baseURL, caseDir, snapshot, options = {}) {
  const uiDir = path.join(caseDir, 'ui');
  ensureDir(uiDir);
  const paths = {
    cowork_panel: path.join('ui', 'cowork-panel.png'),
    project_page: '',
    failure_panel: '',
  };
  await page.screenshot({ path: path.join(caseDir, paths.cowork_panel) });

  const finalReport = snapshot && typeof snapshot.final_report === 'object' ? snapshot.final_report : null;
  const artifactUrl = finalReport ? String(finalReport.entry_artifact_url || '').trim() : '';
  if (artifactUrl) {
    const projectPath = path.join('ui', 'project-page.png');
    const projectPage = await page.context().newPage();
    await projectPage.goto(resolveAbsoluteUrl(baseURL, artifactUrl), { waitUntil: 'domcontentloaded', timeout: 20000 });
    await projectPage.screenshot({ path: path.join(caseDir, projectPath), fullPage: true });
    await projectPage.close();
    paths.project_page = projectPath;
  }

  const terminalStatus = String(snapshot?.status || '').trim();
  if (options.timedOut || ['failed', 'stopped'].includes(terminalStatus)) {
    const failurePath = path.join('ui', 'failure-panel.png');
    await page.screenshot({ path: path.join(caseDir, failurePath), fullPage: true });
    paths.failure_panel = failurePath;
  }
  return paths;
}

function writeCaseRawFiles(caseDir, payloads) {
  ensureDir(caseDir);
  writeJson(path.join(caseDir, 'request.json'), payloads.request || {});
  writeJson(path.join(caseDir, 'snapshot.json'), payloads.snapshot || {});
  writeJson(path.join(caseDir, 'artifacts.json'), payloads.artifacts || {});
  writeText(path.join(caseDir, 'status.log'), Array.isArray(payloads.status_lines) ? payloads.status_lines.join('\n') + '\n' : '');
  writeJson(path.join(caseDir, 'case_result.json'), payloads.case_result || {});
  if (payloads.error_text) {
    writeText(path.join(caseDir, 'error.txt'), String(payloads.error_text));
  }
}

module.exports = {
  appendStatusLine,
  captureCoworkEvidence,
  clearActiveCowork,
  copyArtifactTree,
  ensureDir,
  ensureTargetBots,
  fetchCoworkArtifacts,
  fetchCoworkSnapshot,
  resolveAbsoluteUrl,
  resolveCaseTimeout,
  setBotRole,
  startCoworkViaUi,
  waitCoworkTerminal,
  writeCaseRawFiles,
};
