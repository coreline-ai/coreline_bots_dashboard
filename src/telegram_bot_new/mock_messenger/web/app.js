"use strict";

const tokenInput = document.getElementById("token-input");
const chatIdInput = document.getElementById("chat-id-input");
const userIdInput = document.getElementById("user-id-input");
const messageInput = document.getElementById("message-input");
const webhookUrlInput = document.getElementById("webhook-url-input");
const webhookSecretInput = document.getElementById("webhook-secret-input");
const commandSuggest = document.getElementById("command-suggest");
const timelineList = document.getElementById("timeline-list");
const agentJson = document.getElementById("agent-json");
const diagnosticsJson = document.getElementById("diagnostics-json");
const stateJson = document.getElementById("state-json");
const threadsJson = document.getElementById("threads-json");
const workspace = document.querySelector(".workspace");
const controlsPanel = document.querySelector(".controls");
const statePanel = document.querySelector(".state");
const toggleSessionSectionBtn = document.getElementById("toggle-session-section-btn");
const sessionSectionBody = document.getElementById("session-section-body");
const agentSectionBlock = document.querySelector(".state-block-agent");
const toggleAgentSectionBtn = document.getElementById("toggle-agent-section-btn");
const agentSectionBody = document.getElementById("agent-section-body");

const selectedStatus = document.getElementById("selected-status");
const timelineSessionStatus = document.getElementById("timeline-session-status");
const botList = document.getElementById("bot-list");
const parallelResults = document.getElementById("parallel-results");
const addProfileBtn = document.getElementById("add-profile-btn");
const parallelSendBtn = document.getElementById("parallel-send-btn");
const parallelMessageInput = document.getElementById("parallel-message-input");
const profileDialog = document.getElementById("profile-dialog");
const profileForm = document.getElementById("profile-form");
const profileLabelInput = document.getElementById("profile-label-input");
const profileBotIdInput = document.getElementById("profile-bot-id-input");
const profileChatIdInput = document.getElementById("profile-chat-id-input");
const profileUserIdInput = document.getElementById("profile-user-id-input");
const profileCancelBtn = document.getElementById("profile-cancel-btn");

const refreshStateBtn = document.getElementById("refresh-state-btn");
const toggleEssentialBtn = document.getElementById("toggle-essential-btn");
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const sendBtn = document.getElementById("send-btn");
const clearTimelineBtn = document.getElementById("clear-timeline-btn");
const setWebhookBtn = document.getElementById("set-webhook-btn");
const deleteWebhookBtn = document.getElementById("delete-webhook-btn");
const rateLimitBtn = document.getElementById("rate-limit-btn");

const rateMethodInput = document.getElementById("rate-method-input");
const rateCountInput = document.getElementById("rate-count-input");
const rateRetryInput = document.getElementById("rate-retry-input");

const DEFAULT_TOKEN = "mock_token_1";
const STORAGE_KEY = "mock_messenger_ui_state_v3";
const THEME_STORAGE_KEY = "mock_messenger_theme";
const SESSION_SECTION_STORAGE_KEY = "mock_messenger_session_section_hidden";
const AGENT_SECTION_STORAGE_KEY = "mock_messenger_agent_section_hidden";
const FIXED_THEME = "light";
const SCROLL_BOTTOM_THRESHOLD = 24;
const AUTO_REFRESH_INTERVAL_MS = 1000;
const SIDEBAR_DIAGNOSTICS_REFRESH_MS = 5000;
const YOUTUBE_ID_RE = /^[A-Za-z0-9_-]{11}$/;
const EVENT_LINE_RE = /^\[(\d+|~)\]\[(\d{2}:\d{2}:\d{2})\]\[([a-z_]+)\]\s?(.*)$/i;
const FENCED_CODE_BLOCK_RE = /```([A-Za-z0-9_+-]+)?\n?([\s\S]*?)```/g;
const CODE_LANG_RE = /^[A-Za-z0-9_+-]+$/;
const PROGRESS_EVENT_TYPES = new Set([
  "thread_started",
  "turn_started",
  "reasoning",
  "command_started",
  "command_completed",
  "bridge_status"
]);
const COMMAND_CATALOG = [
  { command: "/start", usage: "/start", nameKo: "시작", description: "봇 시작 안내 메시지를 표시합니다." },
  { command: "/help", usage: "/help", nameKo: "도움말", description: "사용 가능한 명령어 목록을 보여줍니다." },
  { command: "/new", usage: "/new", nameKo: "새 세션", description: "현재 채팅에 새 세션을 생성합니다." },
  { command: "/status", usage: "/status", nameKo: "상태", description: "현재 세션/에이전트/요약 상태를 조회합니다." },
  { command: "/reset", usage: "/reset", nameKo: "초기화", description: "현재 세션을 초기화하고 새 세션으로 전환합니다." },
  { command: "/summary", usage: "/summary", nameKo: "요약 보기", description: "누적 요약(rolling summary)을 출력합니다." },
  { command: "/mode", usage: "/mode ", nameKo: "에이전트 전환", description: "codex/gemini/claude 모드 조회 또는 전환합니다." },
  { command: "/providers", usage: "/providers", nameKo: "제공자 상태", description: "CLI 제공자 설치 여부와 기본 모델을 확인합니다." },
  { command: "/stop", usage: "/stop", nameKo: "실행 중단", description: "현재 실행 중인 turn을 중단 요청합니다." },
  { command: "/youtube", usage: "/youtube ", nameKo: "유튜브 검색", description: "검색어로 유튜브 영상을 찾아 링크를 보냅니다." },
  { command: "/yt", usage: "/yt ", nameKo: "유튜브 검색(축약)", description: "/youtube의 축약 명령입니다." },
  { command: "/echo", usage: "/echo ", nameKo: "에코", description: "입력한 텍스트를 그대로 응답합니다." }
];

let followTimeline = true;
let timelinePointerDown = false;
let lastTimelineSignature = "";
let lastBotListRenderKey = "";
let essentialMode = true;
let latestMessages = [];
let commandSuggestItems = [];
let commandSuggestActiveIndex = -1;
let lastSidebarDiagnosticsAt = 0;
let refreshInFlight = false;
let refreshQueued = false;
let refreshPromise = null;

let catalog = [];
let catalogByBotId = new Map();
let profileDiagnostics = new Map();
let uiState = {
  selected_profile_id: null,
  profiles: []
};

function makeProfileId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `profile_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
}

function numberOrDefault(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) {
    return fallback;
  }
  return Math.trunc(parsed);
}

function currentProfile() {
  if (!uiState.selected_profile_id) {
    return null;
  }
  return uiState.profiles.find((profile) => profile.profile_id === uiState.selected_profile_id) || null;
}

function updateAddProfileButtonState() {
  if (!addProfileBtn) {
    return;
  }
  addProfileBtn.disabled = false;
  addProfileBtn.title = "새 멀티봇 인스턴스를 자동 생성합니다.";
}

function tokenValue() {
  return tokenInput.value.trim();
}

function chatIdValue() {
  return Number(chatIdInput.value || 0);
}

function userIdValue() {
  return Number(userIdInput.value || 0);
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    const profiles = Array.isArray(parsed.profiles)
      ? parsed.profiles
          .map((profile) => ({
            profile_id: String(profile.profile_id || makeProfileId()),
            label: String(profile.label || "Profile"),
            bot_id: String(profile.bot_id || ""),
            token: String(profile.token || ""),
            chat_id: numberOrDefault(profile.chat_id, 1001),
            user_id: numberOrDefault(profile.user_id, 9001),
            selected_for_parallel: profile.selected_for_parallel !== false
          }))
          .filter((profile) => profile.token || profile.bot_id)
      : [];

    return {
      selected_profile_id: parsed.selected_profile_id ? String(parsed.selected_profile_id) : null,
      profiles
    };
  } catch {
    return null;
  }
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(uiState));
}

function applyTheme() {
  document.documentElement.classList.remove("dark");
  document.body.dataset.theme = FIXED_THEME;
  localStorage.setItem(THEME_STORAGE_KEY, FIXED_THEME);
}

function updateThemeButton() {
  if (!themeToggleBtn) {
    return;
  }
  themeToggleBtn.title = "화이트 테마 고정";
  themeToggleBtn.disabled = true;
  themeToggleBtn.setAttribute("aria-disabled", "true");
  const icon = "light_mode";
  themeToggleBtn.innerHTML = `<span class="material-symbols-outlined icon-sm" aria-hidden="true">${icon}</span>`;
}

function initTheme() {
  applyTheme();
  updateThemeButton();
}

function isSectionHidden(storageKey) {
  return localStorage.getItem(storageKey) === "1";
}

function renderSessionToggleButton(hidden) {
  if (!toggleSessionSectionBtn) {
    return;
  }
  const icon = hidden ? "chevron_right" : "chevron_left";
  const label = hidden ? "Session 펼치기" : "Session 최소화";
  toggleSessionSectionBtn.innerHTML = [
    `<span class="material-symbols-outlined" aria-hidden="true">${icon}</span>`,
    `<span class="sr-only">${label}</span>`
  ].join("");
  toggleSessionSectionBtn.title = label;
  toggleSessionSectionBtn.setAttribute("aria-label", label);
  toggleSessionSectionBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
}

function applySessionSectionVisibility(hidden) {
  if (!sessionSectionBody || !toggleSessionSectionBtn) {
    return;
  }
  sessionSectionBody.classList.toggle("is-collapsed", hidden);
  controlsPanel?.classList.toggle("is-collapsed", hidden);
  workspace?.classList.toggle("is-session-collapsed", hidden);
  renderSessionToggleButton(hidden);
}

function renderAgentToggleButton(hidden) {
  if (!toggleAgentSectionBtn) {
    return;
  }
  const icon = hidden ? "chevron_left" : "chevron_right";
  const label = hidden ? "Agent 펼치기" : "Agent 접기";
  toggleAgentSectionBtn.innerHTML = [
    `<span class="material-symbols-outlined" aria-hidden="true">${icon}</span>`,
    `<span class="sr-only">${label}</span>`
  ].join("");
  toggleAgentSectionBtn.title = label;
  toggleAgentSectionBtn.setAttribute("aria-label", label);
  toggleAgentSectionBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
}

function applyAgentSectionVisibility(hidden) {
  if (!agentSectionBody || !toggleAgentSectionBtn) {
    return;
  }
  agentSectionBody.classList.toggle("is-collapsed", hidden);
  agentSectionBlock?.classList.toggle("is-collapsed", hidden);
  statePanel?.classList.toggle("is-collapsed", hidden);
  workspace?.classList.toggle("is-agent-collapsed", hidden);
  renderAgentToggleButton(hidden);
}

function initSectionToggles() {
  if (toggleSessionSectionBtn && sessionSectionBody) {
    const hidden = isSectionHidden(SESSION_SECTION_STORAGE_KEY);
    applySessionSectionVisibility(hidden);
    toggleSessionSectionBtn.addEventListener("click", () => {
      const nextHidden = !sessionSectionBody.classList.contains("is-collapsed");
      localStorage.setItem(SESSION_SECTION_STORAGE_KEY, nextHidden ? "1" : "0");
      applySessionSectionVisibility(nextHidden);
    });
  }
  if (toggleAgentSectionBtn && agentSectionBody) {
    const hidden = isSectionHidden(AGENT_SECTION_STORAGE_KEY);
    applyAgentSectionVisibility(hidden);
    toggleAgentSectionBtn.addEventListener("click", () => {
      const nextHidden = !agentSectionBody.classList.contains("is-collapsed");
      localStorage.setItem(AGENT_SECTION_STORAGE_KEY, nextHidden ? "1" : "0");
      applyAgentSectionVisibility(nextHidden);
    });
  }
}

function upsertCurrentProfileFromInputs() {
  const profile = currentProfile();
  if (!profile) {
    return;
  }
  profile.token = tokenValue();
  profile.chat_id = chatIdValue();
  profile.user_id = userIdValue();

  const catalogRow = catalogByBotId.get(profile.bot_id);
  if (catalogRow && profile.token !== catalogRow.token) {
    profile.bot_id = "";
  }
  saveState();
}

function maskToken(token) {
  if (!token || typeof token !== "string") {
    return "";
  }
  if (token.length <= 10) {
    return token;
  }
  return `${token.slice(0, 4)}...${token.slice(-4)}`;
}

function buildStatusChips(profile, diagnostics) {
  if (!selectedStatus) {
    return;
  }
  const session = diagnostics?.session || {};
  const health = diagnostics?.health?.bot || {};
  const agent = String(session.current_agent || "unknown").toLowerCase();
  const runStatus = String(session.run_status || "idle").toLowerCase();
  const rows = [
    { key: "bot", value: profile?.bot_id || "none", extraClass: "" },
    { key: "agent", value: agent, extraClass: `status-chip--agent-${agent}` },
    { key: "thread", value: session.thread_id || "none", extraClass: "" },
    { key: "run", value: runStatus, extraClass: runStatus === "error" ? "status-chip--run-error" : "" },
    { key: "health", value: health.ok ? "ok" : "down", extraClass: health.ok ? "status-chip--health-ok" : "status-chip--health-down" }
  ];
  selectedStatus.innerHTML = "";
  for (const row of rows) {
    const chip = document.createElement("span");
    chip.className = `status-chip ${row.extraClass}`.trim();
    const key = document.createElement("span");
    key.className = "status-chip-key";
    key.textContent = row.key;
    const value = document.createElement("span");
    value.className = "status-chip-value";
    value.textContent = String(row.value);
    chip.appendChild(key);
    chip.appendChild(value);
    selectedStatus.appendChild(chip);
  }

  if (timelineSessionStatus) {
    const sessionChip = document.createElement("span");
    sessionChip.className = "status-chip status-chip--session-inline";

    const key = document.createElement("span");
    key.className = "status-chip-key";
    key.textContent = "session";

    const value = document.createElement("span");
    value.className = "status-chip-value";
    value.textContent = String(session.session_id || "none");

    sessionChip.appendChild(key);
    sessionChip.appendChild(value);

    timelineSessionStatus.innerHTML = "";
    timelineSessionStatus.appendChild(sessionChip);
  }
}

function renderParallelResults(rows) {
  if (!parallelResults) {
    return;
  }
  if (!Array.isArray(rows) || rows.length === 0) {
    parallelResults.textContent = "아직 실행 결과가 없습니다.";
    return;
  }
  parallelResults.innerHTML = "";
  for (const rawRow of rows) {
    const row = {
      label: String(rawRow?.label || "unknown"),
      status: String(rawRow?.status || "WAIT"),
      detail: String(rawRow?.detail || "running")
    };
    const item = document.createElement("div");
    item.className = "parallel-result-row";

    const label = document.createElement("div");
    label.className = "parallel-result-label";
    label.textContent = row.label;

    const status = document.createElement("div");
    status.textContent = row.status;
    if (row.status === "PASS") {
      status.className = "parallel-status-pass";
    } else if (row.status === "WAIT") {
      status.className = "parallel-status-wait";
    } else {
      status.className = "parallel-status-fail";
    }

    const detail = document.createElement("div");
    detail.className = "parallel-result-detail";
    detail.textContent = row.detail;

    item.appendChild(label);
    item.appendChild(status);
    item.appendChild(detail);
    parallelResults.appendChild(item);
  }
  parallelResults.scrollTop = 0;
}

function setParallelSendBusy(busy) {
  if (!parallelSendBtn) {
    return;
  }
  parallelSendBtn.disabled = busy;
  parallelSendBtn.textContent = busy ? "병렬 전송 실행 중..." : "선택 병렬 전송";
}

function syncWebhookFormFromProfile(profile) {
  if (!profile) {
    return;
  }
  const row = catalogByBotId.get(profile.bot_id);
  if (!row) {
    return;
  }
  const pathSecret = row?.webhook?.path_secret;
  if (row.mode === "embedded" && row.embedded_url && pathSecret) {
    webhookUrlInput.value = `${row.embedded_url}/telegram/webhook/${row.bot_id}/${pathSecret}`;
  } else if (row?.webhook?.public_url) {
    webhookUrlInput.value = String(row.webhook.public_url);
  }
  webhookSecretInput.value = row?.webhook?.secret_token || "";
}

function applyProfileToInputs(profile) {
  if (!profile) {
    tokenInput.value = "";
    chatIdInput.value = "1001";
    userIdInput.value = "9001";
    return;
  }
  tokenInput.value = profile.token || "";
  chatIdInput.value = String(numberOrDefault(profile.chat_id, 1001));
  userIdInput.value = String(numberOrDefault(profile.user_id, 9001));
  syncWebhookFormFromProfile(profile);
}

function selectProfile(profileId) {
  const target = uiState.profiles.find((profile) => profile.profile_id === profileId);
  if (!target) {
    return;
  }
  uiState.selected_profile_id = target.profile_id;
  applyProfileToInputs(target);
  saveState();
  renderBotList();
  lastTimelineSignature = "";
}

function buildBotListRenderKey() {
  if (!Array.isArray(uiState.profiles) || uiState.profiles.length === 0) {
    return `empty:${String(uiState.selected_profile_id || "")}`;
  }
  return uiState.profiles
    .map((profile) => {
      const diag = profileDiagnostics.get(profile.profile_id) || null;
      const session = diag?.session || {};
      const healthOk = diag?.health?.bot?.ok === true ? "1" : "0";
      const provider = String(session.current_agent || "");
      const runStatus = String(session.run_status || "");
      const selected = uiState.selected_profile_id === profile.profile_id ? "1" : "0";
      const checked = profile.selected_for_parallel !== false ? "1" : "0";
      return [
        profile.profile_id,
        profile.label,
        profile.bot_id,
        profile.token,
        profile.chat_id,
        profile.user_id,
        checked,
        selected,
        provider,
        runStatus,
        healthOk,
      ].join("|");
    })
    .join("||");
}

function renderBotList(force = false) {
  if (!botList) {
    return;
  }
  const renderKey = buildBotListRenderKey();
  if (!force && renderKey === lastBotListRenderKey) {
    return;
  }
  lastBotListRenderKey = renderKey;
  botList.innerHTML = "";
  if (!uiState.profiles.length) {
    const empty = document.createElement("div");
    empty.className = "bot-item-empty";
    empty.textContent = "멀티봇 프로필이 없습니다. + 멀티봇 추가를 눌러 시작하세요.";
    botList.appendChild(empty);
    updateAddProfileButtonState();
    return;
  }

  for (const profile of uiState.profiles) {
    const diag = profileDiagnostics.get(profile.profile_id) || null;
    const session = diag?.session || {};
    const healthOk = Boolean(diag?.health?.bot?.ok);
    const catalogRow = catalogByBotId.get(profile.bot_id);
    const provider = session.current_agent || catalogRow?.default_adapter || "unknown";

    const item = document.createElement("div");
    item.className = "bot-item";
    if (uiState.selected_profile_id === profile.profile_id) {
      item.classList.add("is-selected");
    }

    const head = document.createElement("div");
    head.className = "bot-item-head";

    const left = document.createElement("div");
    left.className = "bot-item-main";

    const checkbox = document.createElement("input");
    checkbox.className = "bot-item-check";
    checkbox.type = "checkbox";
    checkbox.checked = profile.selected_for_parallel !== false;
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => {
      profile.selected_for_parallel = checkbox.checked;
      saveState();
    });

    const statusDot = document.createElement("span");
    statusDot.className = `bot-item-status ${healthOk ? "ok" : "fail"}`;

    const title = document.createElement("span");
    title.className = "bot-item-title";
    title.textContent = profile.label;

    left.appendChild(checkbox);
    left.appendChild(statusDot);
    left.appendChild(title);

    const right = document.createElement("div");
    right.className = "bot-item-actions";

    const providerBadge = document.createElement("span");
    providerBadge.className = "bot-item-provider";
    providerBadge.classList.add(`bot-item-provider-${provider}`);
    providerBadge.textContent = provider;
    right.appendChild(providerBadge);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "bot-item-delete-btn";
    deleteBtn.textContent = "삭제";
    deleteBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      void removeBotProfile(profile.profile_id);
    });
    right.appendChild(deleteBtn);

    head.appendChild(left);
    head.appendChild(right);

    const meta = document.createElement("div");
    meta.className = "bot-item-meta";
    const tokenLabel = maskToken(profile.token || "");
    const rows = [
      `bot_id=${profile.bot_id || "(manual)"}`,
      `token=${tokenLabel || "none"}`,
      `chat=${profile.chat_id} user=${profile.user_id}`
    ];
    for (const rowText of rows) {
      const row = document.createElement("div");
      row.className = "bot-item-meta-row";
      row.textContent = rowText;
      meta.appendChild(row);
    }

    item.appendChild(head);
    item.appendChild(meta);
    item.addEventListener("click", () => {
      selectProfile(profile.profile_id);
      refresh();
    });
    botList.appendChild(item);
  }
  updateAddProfileButtonState();
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(`${response.status}: ${JSON.stringify(data)}`);
  }
  return data;
}

async function loadCatalog() {
  try {
    const response = await requestJson("/_mock/bot_catalog");
    catalog = Array.isArray(response?.result?.bots) ? response.result.bots : [];
  } catch {
    catalog = [];
  }
  catalogByBotId = new Map(catalog.map((row) => [String(row.bot_id), row]));
}

function ensureInitialProfileFromParams() {
  const params = new URLSearchParams(window.location.search);
  const paramToken = (params.get("token") || "").trim();
  const paramChatId = numberOrDefault(params.get("chat_id"), 1001);
  const paramUserId = numberOrDefault(params.get("user_id"), 9001);

  if (uiState.profiles.length > 0) {
    return;
  }

  let defaultBot = catalog[0] || null;
  if (paramToken) {
    defaultBot = catalog.find((row) => row.token === paramToken) || defaultBot;
  }
  if (!defaultBot && !paramToken) {
    return;
  }

  uiState.profiles.push({
    profile_id: makeProfileId(),
    label: defaultBot ? `${defaultBot.name} 기본` : "기본 프로필",
    bot_id: defaultBot?.bot_id || "",
    token: paramToken || defaultBot?.token || DEFAULT_TOKEN,
    chat_id: paramChatId,
    user_id: paramUserId,
    selected_for_parallel: true
  });
  uiState.selected_profile_id = uiState.profiles[0].profile_id;
}

function ensureSelectedProfile() {
  if (!uiState.profiles.length) {
    uiState.selected_profile_id = null;
    return;
  }
  const exists = uiState.profiles.some((profile) => profile.profile_id === uiState.selected_profile_id);
  if (!exists) {
    uiState.selected_profile_id = uiState.profiles[0].profile_id;
  }
}

function dedupeProfilesByBotId() {
  if (!Array.isArray(uiState.profiles) || uiState.profiles.length <= 1) {
    return;
  }
  const seen = new Set();
  const nextProfiles = [];
  for (const profile of uiState.profiles) {
    const botId = String(profile?.bot_id || "");
    if (!botId) {
      nextProfiles.push(profile);
      continue;
    }
    if (seen.has(botId)) {
      continue;
    }
    seen.add(botId);
    nextProfiles.push(profile);
  }
  uiState.profiles = nextProfiles;
}

function hydrateProfileDialog() {
  if (!profileBotIdInput) {
    return;
  }
  profileBotIdInput.innerHTML = "";
  for (const row of catalog) {
    const option = document.createElement("option");
    option.value = row.bot_id;
    option.textContent = `${row.name} (${row.bot_id})`;
    profileBotIdInput.appendChild(option);
  }
  if (catalog.length > 0) {
    profileBotIdInput.value = catalog[0].bot_id;
  }
}

async function hydrateInputs() {
  const saved = loadState();
  if (saved) {
    uiState = saved;
  }

  await loadCatalog();
  dedupeProfilesByBotId();
  ensureInitialProfileFromParams();
  ensureSelectedProfile();

  const selected = currentProfile();
  applyProfileToInputs(selected);
  hydrateProfileDialog();
  renderBotList();
  renderParallelResults([]);
  saveState();
}

function hideCommandSuggest() {
  if (!commandSuggest) {
    return;
  }
  commandSuggest.classList.add("hidden");
  commandSuggest.innerHTML = "";
  commandSuggestItems = [];
  commandSuggestActiveIndex = -1;
}

function isCommandSuggestVisible() {
  if (!commandSuggest) {
    return false;
  }
  return !commandSuggest.classList.contains("hidden") && commandSuggestItems.length > 0;
}

function commandQueryToken(text) {
  const raw = String(text || "");
  if (!raw.startsWith("/")) {
    return null;
  }
  const token = raw.slice(1).trimStart().split(/\s+/)[0].toLowerCase();
  return token;
}

function renderCommandSuggest() {
  if (!commandSuggest) {
    return;
  }
  if (commandSuggestItems.length === 0) {
    hideCommandSuggest();
    return;
  }
  const header = document.createElement("div");
  header.className = "command-suggest-header";
  header.textContent = "사용 가능한 명령어 (Tab 또는 클릭으로 입력)";
  commandSuggest.innerHTML = "";
  commandSuggest.appendChild(header);

  commandSuggestItems.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "command-suggest-item";
    if (index === commandSuggestActiveIndex) {
      button.classList.add("is-active");
    }
    button.dataset.commandIndex = String(index);

    const top = document.createElement("div");
    top.className = "command-suggest-top";

    const command = document.createElement("span");
    command.className = "command-suggest-command";
    command.textContent = item.command;
    top.appendChild(command);

    const nameKo = document.createElement("span");
    nameKo.className = "command-suggest-name";
    nameKo.textContent = item.nameKo;
    top.appendChild(nameKo);

    const desc = document.createElement("div");
    desc.className = "command-suggest-desc";
    desc.textContent = item.description;

    button.appendChild(top);
    button.appendChild(desc);
    commandSuggest.appendChild(button);
  });
  commandSuggest.classList.remove("hidden");
}

function applyCommandSuggest(index) {
  if (index < 0 || index >= commandSuggestItems.length) {
    return;
  }
  const selected = commandSuggestItems[index];
  messageInput.value = selected.usage;
  messageInput.focus();
  const cursor = messageInput.value.length;
  messageInput.setSelectionRange(cursor, cursor);
  hideCommandSuggest();
}

function updateCommandSuggest() {
  const token = commandQueryToken(messageInput.value);
  if (token === null) {
    hideCommandSuggest();
    return;
  }

  const nextItems = token
    ? COMMAND_CATALOG.filter((entry) => entry.command.slice(1).startsWith(token))
    : COMMAND_CATALOG.slice();

  commandSuggestItems = nextItems;
  if (commandSuggestItems.length === 0) {
    hideCommandSuggest();
    return;
  }
  if (commandSuggestActiveIndex < 0 || commandSuggestActiveIndex >= commandSuggestItems.length) {
    commandSuggestActiveIndex = 0;
  }
  renderCommandSuggest();
}

function isNearBottom(element) {
  const remain = element.scrollHeight - element.clientHeight - element.scrollTop;
  return remain <= SCROLL_BOTTOM_THRESHOLD;
}

function hasSelectionInTimeline() {
  const selection = window.getSelection ? window.getSelection() : null;
  if (!selection || selection.isCollapsed) {
    return false;
  }
  const anchorIn = selection.anchorNode && timelineList.contains(selection.anchorNode);
  const focusIn = selection.focusNode && timelineList.contains(selection.focusNode);
  return Boolean(anchorIn || focusIn);
}

function appendBubble(kind, text) {
  const shouldFollow = isNearBottom(timelineList) || followTimeline;
  const item = document.createElement("div");
  item.className = `bubble ${kind}`;
  item.textContent = text;
  timelineList.appendChild(item);
  if (shouldFollow) {
    timelineList.scrollTop = timelineList.scrollHeight;
  }
}

function isYoutubeHost(hostname) {
  const host = (hostname || "").toLowerCase();
  return (
    host === "youtube.com" ||
    host === "www.youtube.com" ||
    host === "m.youtube.com" ||
    host === "music.youtube.com" ||
    host === "youtu.be" ||
    host === "www.youtu.be"
  );
}

function extractYoutubeVideoId(rawUrl) {
  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return null;
  }
  if (!isYoutubeHost(parsed.hostname)) {
    return null;
  }

  const host = parsed.hostname.toLowerCase();
  if (host.includes("youtu.be")) {
    const shortId = parsed.pathname.replace(/^\/+/, "").split("/")[0];
    return YOUTUBE_ID_RE.test(shortId) ? shortId : null;
  }

  if (parsed.pathname === "/watch") {
    const v = parsed.searchParams.get("v") || "";
    return YOUTUBE_ID_RE.test(v) ? v : null;
  }

  const parts = parsed.pathname.split("/").filter(Boolean);
  if (parts.length >= 2 && (parts[0] === "shorts" || parts[0] === "embed" || parts[0] === "live")) {
    return YOUTUBE_ID_RE.test(parts[1]) ? parts[1] : null;
  }
  return null;
}

function extractYoutubeLinks(text) {
  if (!text || typeof text !== "string") {
    return [];
  }
  const matches = text.match(/https?:\/\/[^\s<>"']+/gi) || [];
  const seen = new Set();
  const links = [];

  for (const raw of matches) {
    const clean = raw.replace(/[),.;!?]+$/g, "");
    const videoId = extractYoutubeVideoId(clean);
    if (!videoId) {
      continue;
    }
    const key = `${videoId}:${clean}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    links.push({
      videoId,
      url: clean,
      thumbnailUrl: `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`
    });
  }
  return links;
}

function inferYoutubeTitle(text, url) {
  if (!text || typeof text !== "string") {
    return "YouTube Video";
  }
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.includes(url))
    .filter((line) => !/^channel\s*=/i.test(line));
  if (lines.length === 0) {
    return "YouTube Video";
  }
  return lines[0].slice(0, 140);
}

function createYoutubePreview(entry, text) {
  const card = document.createElement("a");
  card.className = "bubble-link-preview bubble-youtube-preview";
  card.href = entry.url;
  card.target = "_blank";
  card.rel = "noopener noreferrer";

  const thumb = document.createElement("img");
  thumb.className = "bubble-youtube-thumb";
  thumb.src = entry.thumbnailUrl;
  thumb.alt = "YouTube thumbnail";
  thumb.loading = "lazy";
  card.appendChild(thumb);

  const meta = document.createElement("div");
  meta.className = "bubble-youtube-meta";

  const title = document.createElement("div");
  title.className = "bubble-youtube-title";
  title.textContent = inferYoutubeTitle(text, entry.url);
  meta.appendChild(title);

  const domain = document.createElement("div");
  domain.className = "bubble-youtube-domain";
  domain.textContent = "youtube.com";
  meta.appendChild(domain);

  card.appendChild(meta);
  return card;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

function renderInlineCodeMarkdownAsHtml(text) {
  const result = [];
  let cursor = 0;
  const inlineCodeRe = /`([^`\n]+)`/g;

  for (const match of text.matchAll(inlineCodeRe)) {
    const start = match.index || 0;
    const before = text.slice(cursor, start);
    if (before) {
      result.push(escapeHtml(before).replace(/\n/g, "<br>"));
    }
    result.push(`<code>${escapeHtml(match[1] || "")}</code>`);
    cursor = start + match[0].length;
  }

  const tail = text.slice(cursor);
  if (tail) {
    result.push(escapeHtml(tail).replace(/\n/g, "<br>"));
  }
  return result.join("");
}

function renderMarkdownCodeAsHtml(text) {
  if (typeof text !== "string" || !/```|`[^`\n]+`/.test(text)) {
    return null;
  }

  const result = [];
  let cursor = 0;
  let hasFencedCode = false;

  for (const match of text.matchAll(FENCED_CODE_BLOCK_RE)) {
    hasFencedCode = true;
    const start = match.index || 0;
    const before = text.slice(cursor, start);
    if (before) {
      result.push(renderInlineCodeMarkdownAsHtml(before));
    }

    const languageRaw = (match[1] || "").trim();
    const language = CODE_LANG_RE.test(languageRaw) ? languageRaw : "";
    const code = escapeHtml(match[2] || "");
    if (language) {
      result.push(`<pre><code class="language-${language}">${code}</code></pre>`);
    } else {
      result.push(`<pre><code>${code}</code></pre>`);
    }
    cursor = start + match[0].length;
  }

  const tail = text.slice(cursor);
  if (tail) {
    result.push(renderInlineCodeMarkdownAsHtml(tail));
  }

  if (hasFencedCode) {
    return result.join("");
  }
  if (/`[^`\n]+`/.test(text)) {
    return renderInlineCodeMarkdownAsHtml(text);
  }
  return null;
}

function isSafeBotHtmlSnippet(text) {
  if (typeof text !== "string" || !text.includes("<")) {
    return false;
  }
  const template = document.createElement("template");
  template.innerHTML = text;
  const stack = Array.from(template.content.childNodes);
  const allowedTags = new Set(["BR", "PRE", "CODE"]);
  const langClassRe = /^language-[A-Za-z0-9_+-]+$/;

  while (stack.length > 0) {
    const node = stack.pop();
    if (!node) {
      continue;
    }
    if (node.nodeType === Node.TEXT_NODE) {
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }

    const element = node;
    if (!allowedTags.has(element.tagName)) {
      return false;
    }

    for (const attr of Array.from(element.attributes)) {
      if (element.tagName === "CODE" && attr.name === "class") {
        if (attr.value && !langClassRe.test(attr.value)) {
          return false;
        }
        continue;
      }
      return false;
    }

    stack.push(...Array.from(element.childNodes));
  }
  return true;
}

function renderBotTextAsHtml(text) {
  if (isSafeBotHtmlSnippet(text)) {
    return text;
  }
  const markdownHtml = renderMarkdownCodeAsHtml(text);
  if (markdownHtml && isSafeBotHtmlSnippet(markdownHtml)) {
    return markdownHtml;
  }
  return null;
}

function timelineSignature(messages) {
  if (!Array.isArray(messages) || messages.length === 0) {
    return essentialMode ? "essential:empty" : "all:empty";
  }
  const base = messages
    .map((msg) => {
      const docId = msg.document && msg.document.id ? msg.document.id : 0;
      const updatedAt = msg.updated_at || 0;
      const textLen = (msg.text || "").length;
      return `${msg.message_id}:${updatedAt}:${docId}:${textLen}`;
    })
    .join("|");
  return `${essentialMode ? "essential" : "all"}:${base}`;
}

function parseEventEnvelope(text) {
  const state = {
    hasEventLines: false,
    hasProgress: false,
    completed: false,
    assistantParts: [],
    errorParts: []
  };
  let currentType = null;
  const lines = (text || "").split(/\r?\n/);

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const match = line.match(EVENT_LINE_RE);
    if (match) {
      const eventType = (match[3] || "").toLowerCase();
      const body = (match[4] || "").trim();
      currentType = eventType;
      state.hasEventLines = true;
      if (PROGRESS_EVENT_TYPES.has(eventType)) {
        state.hasProgress = true;
      }
      if (eventType === "turn_completed") {
        state.completed = true;
      }
      if (eventType === "assistant_message" && body) {
        state.assistantParts.push(body);
      } else if ((eventType === "error" || eventType === "delivery_error") && body) {
        state.errorParts.push(body);
      }
      continue;
    }

    const continuation = line.trim();
    if (!continuation || !currentType) {
      continue;
    }
    if (currentType === "assistant_message") {
      state.assistantParts.push(continuation);
    } else if (currentType === "error" || currentType === "delivery_error") {
      state.errorParts.push(continuation);
    }
  }
  return state;
}

function normalizeJoined(parts) {
  if (!Array.isArray(parts) || parts.length === 0) {
    return "";
  }
  const cleaned = parts
    .map((part) => (typeof part === "string" ? part.trim() : ""))
    .filter(Boolean);
  return cleaned.join("\n").trim();
}

function toEssentialMessage(msg) {
  if (!msg || typeof msg !== "object") {
    return null;
  }
  if (msg.direction !== "bot") {
    return msg;
  }
  const text = typeof msg.text === "string" ? msg.text.trim() : "";
  const hasDocument = Boolean(msg.document && typeof msg.document === "object");

  if (!text) {
    return hasDocument ? msg : null;
  }

  const parsed = parseEventEnvelope(text);
  if (parsed.hasEventLines) {
    const assistantText = normalizeJoined(parsed.assistantParts);
    if (assistantText) {
      return { ...msg, text: assistantText };
    }
    const errorText = normalizeJoined(parsed.errorParts);
    if (errorText) {
      return { ...msg, text: errorText };
    }
    if (parsed.hasProgress && !parsed.completed) {
      return { ...msg, text: "생각중..." };
    }
    return hasDocument ? { ...msg, text: "" } : null;
  }

  if (/^queued turn:/i.test(text)) {
    const queuedAgent = text.match(/\bagent=(codex|gemini|claude)\b/i);
    const agentSuffix = queuedAgent && queuedAgent[1] ? ` (agent=${queuedAgent[1].toLowerCase()})` : "";
    return { ...msg, text: `생각중...${agentSuffix}` };
  }
  if (/^a run is already active/i.test(text)) {
    return { ...msg, text: "생각중..." };
  }
  return msg;
}

function toDisplayMessages(messages) {
  if (!essentialMode) {
    return messages;
  }
  const filtered = [];
  for (const msg of messages) {
    const transformed = toEssentialMessage(msg);
    if (!transformed) {
      continue;
    }
    if ((transformed.text || "").trim() === "생각중..." && filtered.length > 0) {
      const previous = filtered[filtered.length - 1];
      if (
        previous &&
        previous.direction === "bot" &&
        (previous.text || "").trim() === "생각중..." &&
        !previous.document &&
        !transformed.document
      ) {
        filtered[filtered.length - 1] = transformed;
        continue;
      }
    }
    filtered.push(transformed);
  }
  return filtered;
}

function createMessageBubble(msg) {
  const item = document.createElement("div");
  item.className = `bubble ${msg.direction === "bot" ? "bot" : "user"}`;

  const header = document.createElement("div");
  header.className = "bubble-header";
  header.textContent = `[${msg.message_id}]`;
  item.appendChild(header);

  const documentInfo = msg.document && typeof msg.document === "object" ? msg.document : null;
  const defaultDocumentText = documentInfo ? `[document] ${documentInfo.filename}` : "";
  const bodyText = typeof msg.text === "string" ? msg.text.trim() : "";
  const shouldRenderText = bodyText && bodyText !== defaultDocumentText;
  if (shouldRenderText) {
    const textNode = document.createElement("div");
    textNode.className = "bubble-text";
    const renderedBotHtml = msg.direction === "bot" ? renderBotTextAsHtml(bodyText) : null;
    if (renderedBotHtml) {
      textNode.classList.add("bubble-text-html");
      textNode.innerHTML = renderedBotHtml;
    } else {
      textNode.textContent = bodyText;
    }
    item.appendChild(textNode);

    const youtubeLinks = extractYoutubeLinks(bodyText);
    for (const youtubeLink of youtubeLinks) {
      item.appendChild(createYoutubePreview(youtubeLink, bodyText));
    }
  }

  if (documentInfo && typeof documentInfo.url === "string" && documentInfo.url) {
    if (documentInfo.is_image) {
      const image = document.createElement("img");
      image.className = "bubble-image";
      image.src = documentInfo.url;
      image.alt = documentInfo.filename || "image";
      image.loading = "lazy";
      item.appendChild(image);
    } else if (documentInfo.is_html || documentInfo.media_type === "text/html") {
      const frame = document.createElement("iframe");
      frame.className = "bubble-html-preview";
      frame.src = documentInfo.url;
      frame.loading = "lazy";
      frame.title = documentInfo.filename || "html preview";
      frame.referrerPolicy = "no-referrer";
      item.appendChild(frame);

      const openLink = document.createElement("a");
      openLink.className = "bubble-file";
      openLink.href = documentInfo.url;
      openLink.textContent = `Open ${documentInfo.filename || "page"} in new tab`;
      openLink.target = "_blank";
      openLink.rel = "noopener noreferrer";
      item.appendChild(openLink);
    } else {
      const link = document.createElement("a");
      link.className = "bubble-file";
      link.href = documentInfo.url;
      link.textContent = documentInfo.filename || "download file";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.appendChild(link);
    }
  }

  if (documentInfo && !shouldRenderText && documentInfo.filename) {
    const caption = document.createElement("div");
    caption.className = "bubble-caption";
    caption.textContent = documentInfo.filename;
    item.appendChild(caption);
  }
  return item;
}

function renderTimeline(messages) {
  const displayMessages = toDisplayMessages(messages);
  const signature = timelineSignature(displayMessages);
  if (signature === lastTimelineSignature) {
    return;
  }
  if (timelinePointerDown || hasSelectionInTimeline()) {
    return;
  }

  const wasNearBottom = isNearBottom(timelineList);
  const prevScrollTop = timelineList.scrollTop;

  timelineList.innerHTML = "";
  for (const msg of displayMessages) {
    timelineList.appendChild(createMessageBubble(msg));
  }
  lastTimelineSignature = signature;

  if (wasNearBottom || followTimeline) {
    timelineList.scrollTop = timelineList.scrollHeight;
    return;
  }

  const maxTop = Math.max(0, timelineList.scrollHeight - timelineList.clientHeight);
  timelineList.scrollTop = Math.min(prevScrollTop, maxTop);
}

function compactState(result) {
  const state = result?.state ?? {};
  const bots = Array.isArray(state.bots) ? state.bots : [];
  const firstBot = bots[0] || null;
  return {
    allow_get_updates_with_webhook: Boolean(result?.allow_get_updates_with_webhook),
    totals: {
      updates_total: Number(state.updates_total || 0),
      updates_undelivered: Number(state.updates_undelivered || 0),
      messages_total: Number(state.messages_total || 0)
    },
    bot: firstBot
      ? {
          token: maskToken(firstBot.token),
          webhook_enabled: Boolean(firstBot.webhook_url),
          webhook_url: firstBot.webhook_url || null
        }
      : null
  };
}

function inferCurrentAgent(messages) {
  const empty = {
    current_agent: "unknown",
    source: null,
    session_id: null,
    message_id: null
  };
  if (!Array.isArray(messages) || messages.length === 0) {
    return empty;
  }

  let sessionId = null;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    const text = typeof msg?.text === "string" ? msg.text : "";
    if (!sessionId) {
      const sessionMatch = text.match(/(?:^|\n)session=([^\s\n]+)/i);
      if (sessionMatch && sessionMatch[1]) {
        sessionId = sessionMatch[1];
      }
    }

    const queuedMatch = text.match(/\bagent=(codex|gemini|claude)\b/i);
    if (queuedMatch && queuedMatch[1]) {
      return {
        current_agent: queuedMatch[1].toLowerCase(),
        source: "queued_turn",
        session_id: sessionId,
        message_id: msg.message_id ?? null
      };
    }

    const statusMatch = text.match(/(?:^|\n)adapter=(codex|gemini|claude)\b/i);
    if (statusMatch && statusMatch[1]) {
      return {
        current_agent: statusMatch[1].toLowerCase(),
        source: "status",
        session_id: sessionId,
        message_id: msg.message_id ?? null
      };
    }

    const modeSwitchMatch = text.match(/mode switched:\s*(?:codex|gemini|claude)\s*->\s*(codex|gemini|claude)\b/i);
    if (modeSwitchMatch && modeSwitchMatch[1]) {
      return {
        current_agent: modeSwitchMatch[1].toLowerCase(),
        source: "mode_switch",
        session_id: sessionId,
        message_id: msg.message_id ?? null
      };
    }
  }

  return { ...empty, session_id: sessionId };
}

function compactThreads(result, selectedChatId) {
  const rows = Array.isArray(result) ? result : [];
  const normalized = rows.map((row) => ({
    chat_id: row.chat_id,
    message_count: Number(row.message_count || 0),
    webhook_enabled: Boolean(row.webhook_enabled),
    last_updated_at: Number(row.last_updated_at || 0)
  }));

  normalized.sort((a, b) => {
    const aSelected = String(a.chat_id) === String(selectedChatId);
    const bSelected = String(b.chat_id) === String(selectedChatId);
    if (aSelected && !bSelected) {
      return -1;
    }
    if (!aSelected && bSelected) {
      return 1;
    }
    return b.last_updated_at - a.last_updated_at;
  });

  return normalized.slice(0, 10);
}

async function sendTextToProfile(profile, text) {
  await requestJson("/_mock/send", {
    method: "POST",
    body: JSON.stringify({
      token: profile.token,
      chat_id: Number(profile.chat_id),
      user_id: Number(profile.user_id),
      text
    })
  });
}

async function maxMessageIdForProfile(profile) {
  const response = await requestJson(
    `/_mock/messages?token=${encodeURIComponent(profile.token)}&chat_id=${Number(profile.chat_id)}&limit=1`
  );
  const messages = Array.isArray(response?.result?.messages) ? response.result.messages : [];
  if (!messages.length) {
    return 0;
  }
  return Number(messages[messages.length - 1].message_id || 0);
}

function classifyOutcomeFromTexts(texts) {
  const joined = (texts || []).join("\n").toLowerCase();
  if (
    /\bturn_completed\b[\s\S]*?"status"\s*:\s*"error"/i.test(joined) ||
    joined.includes("[error]") ||
    joined.includes("[delivery_error]") ||
    joined.includes("executable not found") ||
    joined.includes("send error")
  ) {
    return { done: true, status: "FAIL", detail: "error" };
  }
  if (joined.includes("turn_completed")) {
    return { done: true, status: "PASS", detail: "turn_completed" };
  }
  if (joined.includes("[assistant_message]")) {
    return { done: true, status: "PASS", detail: "assistant_message" };
  }
  return { done: false, status: "WAIT", detail: "running" };
}

async function waitForParallelOutcome(profile, baselineMessageId, timeoutSec = 60) {
  for (let elapsed = 0; elapsed < timeoutSec; elapsed += 1) {
    const [messagesResp, diagnosticsResp] = await Promise.all([
      requestJson(`/_mock/messages?token=${encodeURIComponent(profile.token)}&chat_id=${Number(profile.chat_id)}&limit=120`),
      requestJson(
        `/_mock/bot_diagnostics?bot_id=${encodeURIComponent(profile.bot_id)}&token=${encodeURIComponent(
          profile.token
        )}&chat_id=${Number(profile.chat_id)}&limit=120`
      ),
    ]);

    const messages = Array.isArray(messagesResp?.result?.messages) ? messagesResp.result.messages : [];
    const texts = messages
      .filter((message) => Number(message.message_id || 0) > baselineMessageId && message.direction === "bot")
      .map((message) => String(message.text || ""));

    const outcome = classifyOutcomeFromTexts(texts);
    if (outcome.done) {
      return outcome;
    }

    const diagnostics = diagnosticsResp?.result || {};
    const runStatus = String(diagnostics?.session?.run_status || "").toLowerCase();
    if (texts.length > 0 && runStatus === "completed") {
      return { done: true, status: "PASS", detail: "run_status=completed" };
    }
    if (runStatus === "error") {
      const tag = String(diagnostics?.last_error_tag || "error");
      return { done: true, status: "FAIL", detail: tag };
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return { done: true, status: "FAIL", detail: "timeout" };
}

async function runParallelSend() {
  const targets = uiState.profiles.filter((profile) => profile.selected_for_parallel !== false);
  if (targets.length < 2) {
    renderParallelResults([
      {
        label: "병렬 전송",
        status: "FAIL",
        detail: "대상 봇을 2개 이상 체크하세요."
      }
    ]);
    appendBubble("meta", "병렬 전송 대상은 2개 이상 선택해야 합니다.");
    return;
  }

  const textSource = parallelMessageInput && parallelMessageInput.value.trim() ? parallelMessageInput.value : messageInput.value;
  const text = textSource.trim();
  if (!text) {
    renderParallelResults([
      {
        label: "병렬 전송",
        status: "FAIL",
        detail: "메시지를 입력하세요."
      }
    ]);
    appendBubble("meta", "병렬 전송할 메시지를 입력하세요.");
    return;
  }
  if (parallelMessageInput && !parallelMessageInput.value.trim()) {
    parallelMessageInput.value = text;
  }

  const results = targets.map((profile) => ({
    label: profile.label,
    status: "WAIT",
    detail: "queued"
  }));
  renderParallelResults(results);
  setParallelSendBusy(true);
  appendBubble("meta", `병렬 전송 시작: ${targets.length}개 대상`);

  try {
    await Promise.all(
      targets.map(async (profile, index) => {
        try {
          const baseline = await maxMessageIdForProfile(profile);
          await sendTextToProfile(profile, text);
          const outcome = await waitForParallelOutcome(profile, baseline, 60);
          results[index] = {
            label: profile.label,
            status: outcome.status,
            detail: outcome.detail
          };
        } catch (error) {
          results[index] = {
            label: profile.label,
            status: "FAIL",
            detail: String(error.message || error)
          };
        }
        renderParallelResults(results);
      })
    );
    appendBubble("meta", "병렬 전송 완료");
    await refresh();
  } finally {
    setParallelSendBusy(false);
  }
}

async function refreshProfileDiagnostics() {
  const jobs = uiState.profiles.map(async (profile) => {
    if (!profile.bot_id || !profile.token) {
      return;
    }
    try {
      const response = await requestJson(
        `/_mock/bot_diagnostics?bot_id=${encodeURIComponent(profile.bot_id)}&token=${encodeURIComponent(
          profile.token
        )}&chat_id=${Number(profile.chat_id)}&limit=80`
      );
      profileDiagnostics.set(profile.profile_id, response.result);
    } catch {
      profileDiagnostics.set(profile.profile_id, {
        health: { bot: { ok: false, error: "diagnostics unavailable" } },
        session: { current_agent: "unknown", run_status: "unknown" },
        metrics: { in_flight_runs: null, worker_heartbeat: { run_worker: null, update_worker: null } },
        last_error_tag: "unknown",
        threads_top10: []
      });
    }
  });
  await Promise.all(jobs);
  renderBotList();
}

async function refreshOnce() {
  const profile = currentProfile();
  if (!profile || !profile.token) {
    latestMessages = [];
    renderTimeline([]);
    if (agentJson) {
      agentJson.textContent = JSON.stringify({ current_agent: "unknown", source: "none" }, null, 2);
    }
    if (diagnosticsJson) {
      diagnosticsJson.textContent = JSON.stringify({ status: "no profile selected" }, null, 2);
    }
    if (stateJson) {
      stateJson.textContent = JSON.stringify({}, null, 2);
    }
    if (threadsJson) {
      threadsJson.textContent = JSON.stringify([], null, 2);
    }
    return;
  }

  try {
    const [messagesResp, stateResp, threadsResp, diagnosticsResp] = await Promise.all([
      requestJson(`/_mock/messages?token=${encodeURIComponent(profile.token)}&chat_id=${Number(profile.chat_id)}&limit=120`),
      requestJson(`/_mock/state?token=${encodeURIComponent(profile.token)}`),
      requestJson(`/_mock/threads?token=${encodeURIComponent(profile.token)}`),
      requestJson(
        `/_mock/bot_diagnostics?bot_id=${encodeURIComponent(profile.bot_id)}&token=${encodeURIComponent(
          profile.token
        )}&chat_id=${Number(profile.chat_id)}&limit=120`
      )
    ]);

    latestMessages = Array.isArray(messagesResp.result.messages) ? messagesResp.result.messages : [];
    renderTimeline(latestMessages);

    const diagnostics = diagnosticsResp.result || {};
    profileDiagnostics.set(profile.profile_id, diagnostics);
    const inferredAgent = inferCurrentAgent(latestMessages);

    if (agentJson) {
      agentJson.textContent = JSON.stringify(diagnostics.session || inferredAgent, null, 2);
    }
    if (diagnosticsJson) {
      diagnosticsJson.textContent = JSON.stringify(
        {
          health: diagnostics.health || null,
          metrics: diagnostics.metrics || null,
          last_error_tag: diagnostics.last_error_tag || "unknown"
        },
        null,
        2
      );
    }
    if (stateJson) {
      stateJson.textContent = JSON.stringify(compactState(stateResp.result), null, 2);
    }
    if (threadsJson) {
      const top = Array.isArray(diagnostics.threads_top10)
        ? diagnostics.threads_top10
        : compactThreads(threadsResp.result, Number(profile.chat_id));
      threadsJson.textContent = JSON.stringify(top, null, 2);
    }

    buildStatusChips(profile, diagnostics);
    const now = Date.now();
    if (now - lastSidebarDiagnosticsAt >= SIDEBAR_DIAGNOSTICS_REFRESH_MS) {
      await refreshProfileDiagnostics();
      lastSidebarDiagnosticsAt = now;
    } else {
      renderBotList();
    }
  } catch (error) {
    appendBubble("meta", `refresh error: ${error.message}`);
  }
}

function refresh() {
  if (refreshInFlight) {
    refreshQueued = true;
    return refreshPromise || Promise.resolve();
  }

  refreshInFlight = true;
  refreshPromise = (async () => {
    do {
      refreshQueued = false;
      await refreshOnce();
    } while (refreshQueued);
  })().finally(() => {
    refreshInFlight = false;
    refreshPromise = null;
  });

  return refreshPromise;
}

function updateEssentialToggleButton() {
  if (!toggleEssentialBtn) {
    return;
  }
  const modeLabel = essentialMode ? "ON" : "OFF";
  toggleEssentialBtn.innerHTML = '<span class="material-symbols-outlined icon-sm" aria-hidden="true">filter_alt</span>';
  const label = `필수 메시지 보기: ${modeLabel}`;
  toggleEssentialBtn.title = label;
  toggleEssentialBtn.setAttribute("aria-label", label);
  toggleEssentialBtn.classList.toggle("is-active", essentialMode);
}

async function handleSendCurrentMessage() {
  const profile = currentProfile();
  const text = messageInput.value.trim();
  if (!profile || !profile.token) {
    appendBubble("meta", `token is required (default: ${DEFAULT_TOKEN})`);
    return;
  }
  if (!text) {
    appendBubble("meta", "message is required");
    return;
  }

  try {
    followTimeline = true;
    await sendTextToProfile(profile, text);
    messageInput.value = "";
    hideCommandSuggest();
    await refresh();
  } catch (error) {
    appendBubble("meta", `send error: ${error.message}`);
  }
}

async function clearCurrentTimeline() {
  const profile = currentProfile();
  if (!profile || !profile.token) {
    appendBubble("meta", `token is required (default: ${DEFAULT_TOKEN})`);
    return;
  }

  const confirmed = globalThis.confirm("현재 채팅 타임라인을 비울까요?");
  if (!confirmed) {
    return;
  }

  try {
    await requestJson("/_mock/messages/clear", {
      method: "POST",
      body: JSON.stringify({
        token: profile.token,
        chat_id: Number(profile.chat_id)
      })
    });
    latestMessages = [];
    lastTimelineSignature = "";
    renderTimeline([]);
    await refresh();
  } catch (error) {
    appendBubble("meta", `timeline clear error: ${error.message}`);
  }
}

function wireQuickActions() {
  for (const button of document.querySelectorAll(".quick-action-btn")) {
    button.addEventListener("click", async () => {
      const cmd = String(button.dataset.command || "").trim();
      if (!cmd) {
        return;
      }
      messageInput.value = cmd;
      await handleSendCurrentMessage();
    });
  }
}

function openProfileDialog() {
  if (!profileDialog) {
    return;
  }
  hydrateProfileDialog();
  const first = catalogByBotId.get(profileBotIdInput.value) || catalog[0];
  profileLabelInput.value = first ? `${first.name} 테스트` : "새 멀티봇";
  profileChatIdInput.value = String(1001);
  profileUserIdInput.value = String(9001);
  profileDialog.showModal();
}

async function addProfileAutomatically() {
  const current = currentProfile();
  const chatId = current ? numberOrDefault(current.chat_id, 1001) : numberOrDefault(chatIdInput.value, 1001);
  const userId = current ? numberOrDefault(current.user_id, 9001) : numberOrDefault(userIdInput.value, 9001);
  const currentCatalogRow = current ? catalogByBotId.get(String(current.bot_id || "")) : null;
  const adapter = String(currentCatalogRow?.default_adapter || "gemini");

  const response = await requestJson("/_mock/bot_catalog/add", {
    method: "POST",
    body: JSON.stringify({ adapter })
  });
  const created = response?.result?.bot;
  if (!created?.bot_id || !created?.token) {
    throw new Error("created bot response is invalid");
  }

  await loadCatalog();

  const profile = {
    profile_id: makeProfileId(),
    label: `${String(created.name || created.bot_id)} 테스트`,
    bot_id: String(created.bot_id),
    token: String(created.token || DEFAULT_TOKEN),
    chat_id: chatId,
    user_id: userId,
    selected_for_parallel: true,
  };

  uiState.profiles.push(profile);
  uiState.selected_profile_id = profile.profile_id;
  applyProfileToInputs(profile);
  saveState();
  renderBotList();
  return true;
}

async function removeBotProfile(profileId) {
  const target = uiState.profiles.find((profile) => profile.profile_id === profileId);
  if (!target) {
    return;
  }

  const botId = String(target.bot_id || "");
  if (botId) {
    const ok = globalThis.confirm(`봇 ${botId}를 삭제하고 연결된 프로필을 제거할까요?`);
    if (!ok) {
      return;
    }
    await requestJson("/_mock/bot_catalog/delete", {
      method: "POST",
      body: JSON.stringify({ bot_id: botId })
    });
    uiState.profiles = uiState.profiles.filter((profile) => String(profile.bot_id || "") !== botId);
  } else {
    uiState.profiles = uiState.profiles.filter((profile) => profile.profile_id !== profileId);
  }

  ensureSelectedProfile();
  await loadCatalog();
  const selected = currentProfile();
  applyProfileToInputs(selected);
  saveState();
  renderBotList();
  await refresh();
}

function closeProfileDialog() {
  if (profileDialog && profileDialog.open) {
    profileDialog.close();
  }
}

function addProfileFromDialog() {
  const botId = String(profileBotIdInput.value || "");
  const row = catalogByBotId.get(botId);
  const duplicate = uiState.profiles.some((profile) => String(profile.bot_id || "") === botId);
  if (botId && duplicate) {
    appendBubble("meta", `중복 bot_id(${botId})는 추가할 수 없습니다.`);
    return;
  }
  const label = String(profileLabelInput.value || "").trim() || (row ? `${row.name} 테스트` : "새 멀티봇");
  const profile = {
    profile_id: makeProfileId(),
    label,
    bot_id: botId,
    token: row?.token || DEFAULT_TOKEN,
    chat_id: numberOrDefault(profileChatIdInput.value, 1001),
    user_id: numberOrDefault(profileUserIdInput.value, 9001),
    selected_for_parallel: true
  };
  uiState.profiles.push(profile);
  uiState.selected_profile_id = profile.profile_id;
  applyProfileToInputs(profile);
  saveState();
  renderBotList();
}

sendBtn.addEventListener("click", handleSendCurrentMessage);
if (clearTimelineBtn) {
  clearTimelineBtn.addEventListener("click", clearCurrentTimeline);
}

messageInput.addEventListener("keydown", (event) => {
  if (isCommandSuggestVisible()) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      commandSuggestActiveIndex = (commandSuggestActiveIndex + 1) % commandSuggestItems.length;
      renderCommandSuggest();
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      commandSuggestActiveIndex =
        (commandSuggestActiveIndex - 1 + commandSuggestItems.length) % commandSuggestItems.length;
      renderCommandSuggest();
      return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      applyCommandSuggest(commandSuggestActiveIndex);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      hideCommandSuggest();
      return;
    }
  }

  if (event.key !== "Enter") {
    return;
  }
  if (event.shiftKey) {
    return;
  }
  if (event.isComposing) {
    return;
  }
  event.preventDefault();
  sendBtn.click();
});

messageInput.addEventListener("input", updateCommandSuggest);
messageInput.addEventListener("focus", updateCommandSuggest);

if (commandSuggest) {
  commandSuggest.addEventListener("mousedown", (event) => {
    event.preventDefault();
  });
  commandSuggest.addEventListener("click", (event) => {
    const target = event.target.closest("[data-command-index]");
    if (!target) {
      return;
    }
    const index = Number(target.dataset.commandIndex || -1);
    applyCommandSuggest(index);
  });
}

setWebhookBtn.addEventListener("click", async () => {
  const token = tokenValue();
  const url = webhookUrlInput.value.trim();
  const secret = webhookSecretInput.value.trim();
  if (!token || !url) {
    appendBubble("meta", "token and webhook url are required");
    return;
  }

  try {
    await requestJson(`/bot${encodeURIComponent(token)}/setWebhook`, {
      method: "POST",
      body: JSON.stringify({
        url,
        secret_token: secret || null,
        drop_pending_updates: false
      })
    });
    await refresh();
  } catch (error) {
    appendBubble("meta", `setWebhook error: ${error.message}`);
  }
});

deleteWebhookBtn.addEventListener("click", async () => {
  const token = tokenValue();
  if (!token) {
    appendBubble("meta", "token is required");
    return;
  }

  try {
    await requestJson(`/bot${encodeURIComponent(token)}/deleteWebhook`, {
      method: "POST",
      body: JSON.stringify({ drop_pending_updates: false })
    });
    await refresh();
  } catch (error) {
    appendBubble("meta", `deleteWebhook error: ${error.message}`);
  }
});

rateLimitBtn.addEventListener("click", async () => {
  const token = tokenValue();
  if (!token) {
    appendBubble("meta", "token is required");
    return;
  }
  try {
    await requestJson("/_mock/rate_limit", {
      method: "POST",
      body: JSON.stringify({
        token,
        method: rateMethodInput.value,
        count: Number(rateCountInput.value || 1),
        retry_after: Number(rateRetryInput.value || 1)
      })
    });
    appendBubble("meta", "rate limit rule applied");
  } catch (error) {
    appendBubble("meta", `rate-limit error: ${error.message}`);
  }
});

refreshStateBtn.addEventListener("click", refresh);
toggleEssentialBtn.addEventListener("click", () => {
  essentialMode = !essentialMode;
  followTimeline = isNearBottom(timelineList);
  lastTimelineSignature = "";
  updateEssentialToggleButton();
  renderTimeline(latestMessages);
});
if (addProfileBtn) {
  addProfileBtn.addEventListener("click", async () => {
    try {
      await addProfileAutomatically();
      await refresh();
    } catch (error) {
      appendBubble("meta", `멀티봇 추가 실패: ${error.message}`);
    }
  });
}

if (parallelSendBtn) {
  parallelSendBtn.addEventListener("click", runParallelSend);
}

if (parallelMessageInput) {
  parallelMessageInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    if (parallelSendBtn) {
      parallelSendBtn.click();
    }
  });
}

if (profileCancelBtn) {
  profileCancelBtn.addEventListener("click", closeProfileDialog);
}

if (profileForm) {
  profileForm.addEventListener("submit", (event) => {
    event.preventDefault();
    addProfileFromDialog();
    closeProfileDialog();
    refresh();
  });
}

[tokenInput, chatIdInput, userIdInput].forEach((input) => {
  input.addEventListener("change", () => {
    upsertCurrentProfileFromInputs();
    renderBotList();
    refresh();
  });
});

webhookUrlInput.addEventListener("change", saveState);
webhookSecretInput.addEventListener("change", saveState);
timelineList.addEventListener("scroll", () => {
  followTimeline = isNearBottom(timelineList);
});
timelineList.addEventListener("pointerdown", () => {
  timelinePointerDown = true;
});
window.addEventListener("pointerup", () => {
  timelinePointerDown = false;
});

setInterval(() => {
  void refresh();
}, AUTO_REFRESH_INTERVAL_MS);
initTheme();
initSectionToggles();
hydrateInputs().then(async () => {
  wireQuickActions();
  updateEssentialToggleButton();
  await refreshProfileDiagnostics();
  await refresh();
});
