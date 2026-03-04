"use strict";

const tokenInput = document.getElementById("token-input");
const chatIdInput = document.getElementById("chat-id-input");
const userIdInput = document.getElementById("user-id-input");
const sessionProjectSelect = document.getElementById("session-project-select");
const sessionSkillSelect = document.getElementById("session-skill-select");
const sessionRoleSelect = document.getElementById("session-role-select");
const botIdInput = document.getElementById("bot-id-input");
const messageInput = document.getElementById("message-input");
const webhookUrlInput = document.getElementById("webhook-url-input");
const webhookSecretInput = document.getElementById("webhook-secret-input");
const commandSuggest = document.getElementById("command-suggest");
const timelineList = document.getElementById("timeline-list");
const agentJson = document.getElementById("agent-json");
const diagnosticsJson = document.getElementById("diagnostics-json");
const stateJson = document.getElementById("state-json");
const threadsJson = document.getElementById("threads-json");
const auditJson = document.getElementById("audit-json");
const auditError = document.getElementById("audit-error");
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
const parallelResultsBody = document.getElementById("parallel-results-body");
const toggleParallelResultsBtn = document.getElementById("toggle-parallel-results-btn");
const addProfileBtn = document.getElementById("add-profile-btn");
const parallelSendBtn = document.getElementById("parallel-send-btn");
const parallelMessageInput = document.getElementById("parallel-message-input");
const debatePanel = document.getElementById("debate-panel");
const debatePanelBody = document.getElementById("debate-panel-body");
const debateMeta = document.getElementById("debate-meta");
const debateCurrentTurn = document.getElementById("debate-current-turn");
const debateTurns = document.getElementById("debate-turns");
const debateErrors = document.getElementById("debate-errors");
const debateStopBtn = document.getElementById("debate-stop-btn");
const toggleDebatePanelBtn = document.getElementById("toggle-debate-panel-btn");
const coworkPanel = document.getElementById("cowork-panel");
const coworkPanelBody = document.getElementById("cowork-panel-body");
const coworkMeta = document.getElementById("cowork-meta");
const coworkCurrentStage = document.getElementById("cowork-current-stage");
const coworkStages = document.getElementById("cowork-stages");
const coworkTasks = document.getElementById("cowork-tasks");
const coworkErrors = document.getElementById("cowork-errors");
const coworkFinal = document.getElementById("cowork-final");
const coworkArtifacts = document.getElementById("cowork-artifacts");
const coworkStopBtn = document.getElementById("cowork-stop-btn");
const toggleCoworkPanelBtn = document.getElementById("toggle-cowork-panel-btn");
const towerPanelBody = document.getElementById("tower-panel-body");
const toggleTowerPanelBtn = document.getElementById("toggle-tower-panel-btn");
const towerMeta = document.getElementById("tower-meta");
const towerList = document.getElementById("tower-list");
const towerRefreshBtn = document.getElementById("tower-refresh-btn");
const runtimeProfileMeta = document.getElementById("runtime-profile-meta");
const profileDialog = document.getElementById("profile-dialog");
const profileForm = document.getElementById("profile-form");
const profileLabelInput = document.getElementById("profile-label-input");
const profileBotIdInput = document.getElementById("profile-bot-id-input");
const profileChatIdInput = document.getElementById("profile-chat-id-input");
const profileUserIdInput = document.getElementById("profile-user-id-input");
const profileCancelBtn = document.getElementById("profile-cancel-btn");

const refreshStateBtn = document.getElementById("refresh-state-btn");
const openTalkViewerBtn = document.getElementById("open-talk-viewer-btn");
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
const talkViewerOverlay = document.getElementById("talk-viewer-overlay");
const talkViewerBackdrop = document.getElementById("talk-viewer-backdrop");
const talkViewerBody = document.getElementById("talk-viewer-body");
const talkViewerMeta = document.getElementById("talk-viewer-meta");
const talkViewerCloseBtn = document.getElementById("talk-viewer-close-btn");
const talkViewerClearBtn = document.getElementById("talk-viewer-clear-btn");

const DEFAULT_TOKEN = "mock_token_a";
const STORAGE_KEY = "mock_messenger_ui_state_v4";
const LEGACY_STORAGE_KEYS = ["mock_messenger_ui_state_v3"];
const THEME_STORAGE_KEY = "mock_messenger_theme";
const SESSION_SECTION_STORAGE_KEY = "mock_messenger_session_section_hidden";
const SESSION_ACCORDION_STORAGE_KEY_PREFIX = "mock_messenger_session_group_hidden_";
const AGENT_SECTION_STORAGE_KEY = "mock_messenger_agent_section_hidden";
const PARALLEL_RESULTS_COLLAPSE_STORAGE_KEY = "mock_messenger_parallel_results_hidden";
const DEBATE_PANEL_COLLAPSE_STORAGE_KEY = "mock_messenger_debate_panel_hidden";
const COWORK_PANEL_COLLAPSE_STORAGE_KEY = "mock_messenger_cowork_panel_hidden";
const TOWER_PANEL_COLLAPSE_STORAGE_KEY = "mock_messenger_tower_panel_hidden";
const FIXED_THEME = "light";
const SCROLL_BOTTOM_THRESHOLD = 24;
const AUTO_REFRESH_INTERVAL_MS = 1000;
const SIDEBAR_DIAGNOSTICS_REFRESH_MS = 5000;
const TALK_VIEWER_MAX_ENTRIES = 500;
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
  { command: "/model", usage: "/model ", nameKo: "모델 전환", description: "현재 provider의 모델 조회 또는 전환합니다." },
  { command: "/skills", usage: "/skills", nameKo: "스킬 목록", description: "설치된 스킬 목록을 확인합니다." },
  { command: "/skill", usage: "/skill ", nameKo: "스킬 적용", description: "현재 세션에 스킬을 적용/해제합니다." },
  { command: "/project", usage: "/project ", nameKo: "프로젝트 경로", description: "세션 작업 경로를 조회/변경합니다." },
  { command: "/unsafe", usage: "/unsafe ", nameKo: "Unsafe 모드", description: "시간 제한 unsafe 모드를 on/off 합니다." },
  { command: "/providers", usage: "/providers", nameKo: "제공자 상태", description: "CLI 제공자 설치 여부와 기본 모델을 확인합니다." },
  { command: "/stop", usage: "/stop", nameKo: "실행 중단", description: "현재 실행 중인 turn을 중단 요청합니다." },
  { command: "/youtube", usage: "/youtube ", nameKo: "유튜브 검색", description: "검색어로 유튜브 영상을 찾아 링크를 보냅니다." },
  { command: "/yt", usage: "/yt ", nameKo: "유튜브 검색(축약)", description: "/youtube의 축약 명령입니다." },
  { command: "/echo", usage: "/echo ", nameKo: "에코", description: "입력한 텍스트를 그대로 응답합니다." },
  { command: "/talk", usage: "/talk ", nameKo: "자유 대화", description: "선택된 멀티봇 자유 대화를 라운드 기반으로 실행합니다." },
  { command: "/relay", usage: "/relay ", nameKo: "릴레이", description: "멀티봇이 대사를 순서대로 이어가는 릴레이를 실행합니다." },
  { command: "/pitchbattle", usage: "/pitchbattle ", nameKo: "피치 배틀", description: "아이디어 피치 배틀 후 판정 턴을 수행합니다." },
  { command: "/quizbattle", usage: "/quizbattle ", nameKo: "퀴즈 배틀", description: "퀴즈마스터 기반 배틀 후 판정 턴을 수행합니다." },
  { command: "/debate-lite", usage: "/debate-lite ", nameKo: "경량 토론", description: "짧은 찬반 토론 후 판정 턴을 수행합니다." },
  { command: "/improv", usage: "/improv ", nameKo: "즉흥극", description: "상황극을 라운드-로빈으로 이어갑니다." },
  { command: "/quest", usage: "/quest ", nameKo: "퀘스트", description: "협동 퀘스트 수행 후 성공/실패를 판정합니다." },
  { command: "/memechain", usage: "/memechain ", nameKo: "밈 체인", description: "한 줄 밈을 이어가는 체인을 실행합니다." },
  { command: "/court", usage: "/court ", nameKo: "법정극", description: "역할 기반 법정극 진행 후 판결을 선언합니다." }
];
const PLAY_COMMAND_KEYS = [
  "relay",
  "pitchbattle",
  "quizbattle",
  "debate-lite",
  "improv",
  "quest",
  "memechain",
  "court",
];
const SUPPORTED_PROVIDER_OPTIONS = ["codex", "gemini", "claude"];
const SUPPORTED_ROLE_OPTIONS = ["controller", "planner", "executor", "integrator"];
const FALLBACK_AVAILABLE_MODELS = {
  codex: [
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.2",
    "gpt-5.1-codex-mini",
    "gpt-5"
  ],
  gemini: ["gemini-2.5-pro", "gemini-2.5-flash"],
  claude: ["claude-sonnet-4-5"]
};

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
let projectCatalog = [];
let skillCatalog = [];
let uiState = {
  selected_profile_id: null,
  profiles: [],
  active_debate_id: null,
  active_debate_scope_key: null,
  active_cowork_id: null
};
let parallelSendBusy = false;
let debateBusy = false;
let debatePollingTimer = null;
let debateLastStatus = "";
let coworkBusy = false;
let coworkPollingTimer = null;
let coworkLastStatus = "";
let towerRecoverBusy = false;
let talkViewerOpen = false;
let talkViewerEntries = [];
let talkViewerSession = {
  status: "idle",
  mode: "talk",
  title: "",
  seed: "",
  rounds: 0,
  participants: 0,
  passCount: 0,
  failCount: 0,
  verdict: "",
};
const profileModelApplyBusy = new Set();
let loadedStateFromLegacy = false;

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

function providerDefaultModel(catalogRow, provider) {
  const modelsByProvider = catalogRow?.default_models && typeof catalogRow.default_models === "object"
    ? catalogRow.default_models
    : null;
  const raw = modelsByProvider ? modelsByProvider[provider] : null;
  if (!raw || typeof raw !== "string") {
    return "";
  }
  return raw.trim();
}

function availableModelsForProvider(catalogRow, provider) {
  const fromCatalog = catalogRow?.available_models && typeof catalogRow.available_models === "object"
    ? catalogRow.available_models[provider]
    : null;
  if (Array.isArray(fromCatalog)) {
    const normalized = fromCatalog
      .map((item) => String(item || "").trim())
      .filter((item) => item.length > 0);
    if (normalized.length > 0) {
      return normalized;
    }
  }
  const fallback = FALLBACK_AVAILABLE_MODELS[provider];
  return Array.isArray(fallback) ? [...fallback] : [];
}

function normalizeProvider(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (SUPPORTED_PROVIDER_OPTIONS.includes(normalized)) {
    return normalized;
  }
  return "";
}

function resolveProfileProvider(profile, diagnostics, catalogRow) {
  const diagnosticProvider = normalizeProvider(diagnostics?.session?.current_agent);
  if (diagnosticProvider) {
    return diagnosticProvider;
  }
  const selectedProvider = normalizeProvider(profile?.selected_provider);
  if (selectedProvider) {
    return selectedProvider;
  }
  const defaultProvider = normalizeProvider(catalogRow?.default_adapter);
  if (defaultProvider) {
    return defaultProvider;
  }
  return "codex";
}

function resolveProfileModel(profile, diagnostics, catalogRow, provider) {
  const models = availableModelsForProvider(catalogRow, provider);
  if (!models.length) {
    return "";
  }
  const diagnosticModel = String(diagnostics?.session?.current_model || "").trim();
  if (diagnosticModel && models.includes(diagnosticModel)) {
    return diagnosticModel;
  }
  const selectedModel = String(profile?.selected_model || "").trim();
  if (selectedModel && models.includes(selectedModel)) {
    return selectedModel;
  }
  const defaultModel = providerDefaultModel(catalogRow, provider);
  if (defaultModel && models.includes(defaultModel)) {
    return defaultModel;
  }
  return models[0];
}

function normalizeProjectPath(value) {
  return String(value || "").trim();
}

function normalizeSkillIds(value) {
  const raw = Array.isArray(value) ? value.map((item) => String(item || "")) : String(value || "").split(",");
  const deduped = [];
  const seen = new Set();
  for (const row of raw) {
    const token = String(row || "").trim();
    if (!token || seen.has(token)) {
      continue;
    }
    seen.add(token);
    deduped.push(token);
  }
  return deduped;
}

function resolveProfileSkills(profile, diagnostics) {
  const diagnosticSkills = normalizeSkillIds(diagnostics?.session?.current_skill);
  if (diagnosticSkills.length > 0) {
    return diagnosticSkills;
  }
  return normalizeSkillIds(profile?.selected_skill);
}

function resolveProfileProject(profile, diagnostics) {
  const diagnosticProject = normalizeProjectPath(diagnostics?.session?.current_project);
  if (diagnosticProject) {
    return diagnosticProject;
  }
  return normalizeProjectPath(profile?.selected_project);
}

function normalizeRole(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (SUPPORTED_ROLE_OPTIONS.includes(normalized)) {
    return normalized;
  }
  return "executor";
}

function resolveProfileRole(profile, catalogRow) {
  const selectedRole = normalizeRole(profile?.selected_role);
  if (selectedRole) {
    return selectedRole;
  }
  const defaultRole = normalizeRole(catalogRow?.default_role);
  if (defaultRole) {
    return defaultRole;
  }
  return "executor";
}

function parseUnsafeUntil(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  const text = String(value || "").trim();
  if (/^\d+$/.test(text)) {
    return Number(text);
  }
  return null;
}

function formatUnsafeRemaining(unsafeUntil) {
  const ts = parseUnsafeUntil(unsafeUntil);
  if (!ts) {
    return "off";
  }
  const deltaMs = ts - Date.now();
  if (deltaMs <= 0) {
    return "expired";
  }
  const totalSec = Math.max(0, Math.floor(deltaMs / 1000));
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
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
  loadedStateFromLegacy = false;
  const stateKeys = [STORAGE_KEY, ...LEGACY_STORAGE_KEYS];
  for (const key of stateKeys) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) {
        continue;
      }
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") {
        continue;
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
              selected_for_parallel: profile.selected_for_parallel !== false,
              selected_provider: String(profile.selected_provider || ""),
              selected_model: String(profile.selected_model || ""),
              selected_skill: String(profile.selected_skill || ""),
              selected_project: String(profile.selected_project || ""),
              selected_role: normalizeRole(profile.selected_role || "")
            }))
            .filter((profile) => profile.token || profile.bot_id)
        : [];

      loadedStateFromLegacy = key !== STORAGE_KEY;
      return {
        selected_profile_id: parsed.selected_profile_id ? String(parsed.selected_profile_id) : null,
        profiles,
        active_debate_id: parsed.active_debate_id ? String(parsed.active_debate_id) : null,
        active_debate_scope_key: parsed.active_debate_scope_key ? String(parsed.active_debate_scope_key) : null,
        active_cowork_id: parsed.active_cowork_id ? String(parsed.active_cowork_id) : null
      };
    } catch {
      continue;
    }
  }
  return null;
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

function renderSessionAccordionToggleButton(button, hidden) {
  if (!button) {
    return;
  }
  const icon = hidden ? "expand_more" : "expand_less";
  button.classList.toggle("is-collapsed", hidden);
  button.setAttribute("aria-expanded", hidden ? "false" : "true");
  const iconNode = button.querySelector(".session-accordion-icon");
  if (iconNode) {
    iconNode.textContent = icon;
  }
}

function applySessionAccordionVisibility(button, body, hidden) {
  if (!button || !body) {
    return;
  }
  body.classList.toggle("is-collapsed", hidden);
  renderSessionAccordionToggleButton(button, hidden);
}

function initSessionAccordions() {
  if (!sessionSectionBody) {
    return;
  }
  const toggles = Array.from(sessionSectionBody.querySelectorAll(".session-accordion-toggle"));
  for (const button of toggles) {
    const targetId = String(button.dataset.sessionAccordionTarget || "").trim();
    if (!targetId) {
      continue;
    }
    const body = document.getElementById(targetId);
    if (!body) {
      continue;
    }
    const key = String(button.dataset.sessionAccordionKey || targetId).trim();
    const storageKey = `${SESSION_ACCORDION_STORAGE_KEY_PREFIX}${key}`;
    const hidden = isSectionHidden(storageKey);
    applySessionAccordionVisibility(button, body, hidden);
    button.addEventListener("click", () => {
      const nextHidden = !body.classList.contains("is-collapsed");
      localStorage.setItem(storageKey, nextHidden ? "1" : "0");
      applySessionAccordionVisibility(button, body, nextHidden);
    });
  }
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

function renderParallelResultsToggleButton(hidden) {
  if (!toggleParallelResultsBtn) {
    return;
  }
  const icon = hidden ? "expand_more" : "expand_less";
  const label = hidden ? "Parallel Results 펼치기" : "Parallel Results 접기";
  toggleParallelResultsBtn.innerHTML = [
    `<span class="material-symbols-outlined" aria-hidden="true">${icon}</span>`,
    `<span class="sr-only">${label}</span>`
  ].join("");
  toggleParallelResultsBtn.title = label;
  toggleParallelResultsBtn.setAttribute("aria-label", label);
  toggleParallelResultsBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
}

function applyParallelResultsVisibility(hidden) {
  if (!parallelResultsBody) {
    return;
  }
  parallelResultsBody.classList.toggle("is-collapsed", hidden);
  renderParallelResultsToggleButton(hidden);
}

function initParallelResultsToggle() {
  if (!toggleParallelResultsBtn || !parallelResultsBody) {
    return;
  }
  const hidden = isSectionHidden(PARALLEL_RESULTS_COLLAPSE_STORAGE_KEY);
  applyParallelResultsVisibility(hidden);
  toggleParallelResultsBtn.addEventListener("click", () => {
    const nextHidden = !parallelResultsBody.classList.contains("is-collapsed");
    localStorage.setItem(PARALLEL_RESULTS_COLLAPSE_STORAGE_KEY, nextHidden ? "1" : "0");
    applyParallelResultsVisibility(nextHidden);
  });
}

function renderDebatePanelToggleButton(hidden) {
  if (!toggleDebatePanelBtn) {
    return;
  }
  const icon = hidden ? "expand_more" : "expand_less";
  const label = hidden ? "Debate Panel 펼치기" : "Debate Panel 접기";
  toggleDebatePanelBtn.innerHTML = [
    `<span class="material-symbols-outlined" aria-hidden="true">${icon}</span>`,
    `<span class="sr-only">${label}</span>`
  ].join("");
  toggleDebatePanelBtn.title = label;
  toggleDebatePanelBtn.setAttribute("aria-label", label);
  toggleDebatePanelBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
}

function applyDebatePanelVisibility(hidden) {
  if (!debatePanelBody) {
    return;
  }
  debatePanelBody.classList.toggle("is-collapsed", hidden);
  renderDebatePanelToggleButton(hidden);
}

function initDebatePanelToggle() {
  if (!toggleDebatePanelBtn || !debatePanelBody) {
    return;
  }
  const hidden = isSectionHidden(DEBATE_PANEL_COLLAPSE_STORAGE_KEY);
  applyDebatePanelVisibility(hidden);
  toggleDebatePanelBtn.addEventListener("click", () => {
    const nextHidden = !debatePanelBody.classList.contains("is-collapsed");
    localStorage.setItem(DEBATE_PANEL_COLLAPSE_STORAGE_KEY, nextHidden ? "1" : "0");
    applyDebatePanelVisibility(nextHidden);
  });
}

function renderCoworkPanelToggleButton(hidden) {
  if (!toggleCoworkPanelBtn) {
    return;
  }
  const icon = hidden ? "expand_more" : "expand_less";
  const label = hidden ? "Cowork Panel 펼치기" : "Cowork Panel 접기";
  toggleCoworkPanelBtn.innerHTML = [
    `<span class="material-symbols-outlined" aria-hidden="true">${icon}</span>`,
    `<span class="sr-only">${label}</span>`
  ].join("");
  toggleCoworkPanelBtn.title = label;
  toggleCoworkPanelBtn.setAttribute("aria-label", label);
  toggleCoworkPanelBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
}

function applyCoworkPanelVisibility(hidden) {
  if (!coworkPanelBody) {
    return;
  }
  coworkPanelBody.classList.toggle("is-collapsed", hidden);
  renderCoworkPanelToggleButton(hidden);
}

function initCoworkPanelToggle() {
  if (!toggleCoworkPanelBtn || !coworkPanelBody) {
    return;
  }
  const hidden = isSectionHidden(COWORK_PANEL_COLLAPSE_STORAGE_KEY);
  applyCoworkPanelVisibility(hidden);
  toggleCoworkPanelBtn.addEventListener("click", () => {
    const nextHidden = !coworkPanelBody.classList.contains("is-collapsed");
    localStorage.setItem(COWORK_PANEL_COLLAPSE_STORAGE_KEY, nextHidden ? "1" : "0");
    applyCoworkPanelVisibility(nextHidden);
  });
}

function renderTowerPanelToggleButton(hidden) {
  if (!toggleTowerPanelBtn) {
    return;
  }
  const icon = hidden ? "expand_more" : "expand_less";
  const label = hidden ? "Control Tower 펼치기" : "Control Tower 접기";
  toggleTowerPanelBtn.innerHTML = [
    `<span class="material-symbols-outlined" aria-hidden="true">${icon}</span>`,
    `<span class="sr-only">${label}</span>`
  ].join("");
  toggleTowerPanelBtn.title = label;
  toggleTowerPanelBtn.setAttribute("aria-label", label);
  toggleTowerPanelBtn.setAttribute("aria-expanded", hidden ? "false" : "true");
}

function applyTowerPanelVisibility(hidden) {
  if (!towerPanelBody) {
    return;
  }
  towerPanelBody.classList.toggle("is-collapsed", hidden);
  renderTowerPanelToggleButton(hidden);
}

function initTowerPanelToggle() {
  if (!toggleTowerPanelBtn || !towerPanelBody) {
    return;
  }
  const hidden = isSectionHidden(TOWER_PANEL_COLLAPSE_STORAGE_KEY);
  applyTowerPanelVisibility(hidden);
  toggleTowerPanelBtn.addEventListener("click", () => {
    const nextHidden = !towerPanelBody.classList.contains("is-collapsed");
    localStorage.setItem(TOWER_PANEL_COLLAPSE_STORAGE_KEY, nextHidden ? "1" : "0");
    applyTowerPanelVisibility(nextHidden);
  });
}

function updateTalkViewerToggleButton() {
  if (!openTalkViewerBtn) {
    return;
  }
  const running = talkViewerSession.status === "running";
  openTalkViewerBtn.classList.toggle("is-active", talkViewerOpen || running);
  const label = talkViewerOpen ? "Talk/Play Viewer 닫기" : running ? "Talk/Play Viewer 보기(실행 중)" : "Talk/Play Viewer 열기";
  openTalkViewerBtn.title = label;
  openTalkViewerBtn.setAttribute("aria-label", label);
}

function setTalkViewerOpen(open) {
  talkViewerOpen = Boolean(open);
  if (talkViewerOverlay) {
    talkViewerOverlay.classList.toggle("hidden", !talkViewerOpen);
    talkViewerOverlay.setAttribute("aria-hidden", talkViewerOpen ? "false" : "true");
  }
  document.body.classList.toggle("talk-viewer-open", talkViewerOpen);
  updateTalkViewerToggleButton();
  if (talkViewerOpen) {
    renderTalkViewer(true);
  }
}

function setTalkViewerSession(nextState) {
  talkViewerSession = {
    ...talkViewerSession,
    ...(nextState && typeof nextState === "object" ? nextState : {}),
  };
  renderTalkViewerMeta();
  updateTalkViewerToggleButton();
}

function clearTalkViewer() {
  talkViewerEntries = [];
  talkViewerSession = {
    status: "idle",
    mode: "talk",
    title: "",
    seed: "",
    rounds: 0,
    participants: 0,
    passCount: 0,
    failCount: 0,
    verdict: "",
  };
  renderTalkViewerMeta();
  renderTalkViewer(true);
  updateTalkViewerToggleButton();
}

function renderTalkViewerMeta() {
  if (!talkViewerMeta) {
    return;
  }
  const status = String(talkViewerSession.status || "idle");
  const mode = String(talkViewerSession.mode || "talk").trim() || "talk";
  const title = String(talkViewerSession.title || "").trim();
  if (!talkViewerEntries.length && status === "idle") {
    talkViewerMeta.textContent = "대화 기록이 없습니다.";
    return;
  }
  const seed = String(talkViewerSession.seed || "").trim();
  const seedPreview = seed ? ` · "${seed.slice(0, 36)}${seed.length > 36 ? "..." : ""}"` : "";
  const rounds = Number(talkViewerSession.rounds || 0);
  const participants = Number(talkViewerSession.participants || 0);
  const passCount = Number(talkViewerSession.passCount || 0);
  const failCount = Number(talkViewerSession.failCount || 0);
  const verdict = String(talkViewerSession.verdict || "").trim() || "-";
  const titleChunk = title ? `title=${title} · ` : "";
  const base = `${titleChunk}mode=${mode} · status=${status} · rounds=${rounds} · participants=${participants} · pass=${passCount} · fail=${failCount} · verdict=${verdict}`;
  talkViewerMeta.textContent = `${base}${seedPreview}`;
}

function appendTalkViewerEntry(entry) {
  if (!entry || typeof entry !== "object") {
    return;
  }
  const text = String(entry.text || "").trim();
  if (!text) {
    return;
  }
  const speaker = String(entry.speaker || "bot").trim() || "bot";
  const type = String(entry.type || "bot").trim().toLowerCase();
  const provider = normalizeProvider(entry.provider);
  talkViewerEntries.push({
    speaker,
    text,
    type,
    provider,
    created_at: Date.now(),
  });
  if (talkViewerEntries.length > TALK_VIEWER_MAX_ENTRIES) {
    talkViewerEntries = talkViewerEntries.slice(talkViewerEntries.length - TALK_VIEWER_MAX_ENTRIES);
  }
  renderTalkViewer();
  renderTalkViewerMeta();
}

function renderTalkViewer(forceBottom = false) {
  if (!talkViewerBody) {
    return;
  }
  const shouldFollow = forceBottom || isNearBottom(talkViewerBody);
  talkViewerBody.innerHTML = "";
  if (!talkViewerEntries.length) {
    const empty = document.createElement("div");
    empty.className = "talk-viewer-empty";
    empty.textContent = "아직 Talk/Play 로그가 없습니다. /talk 또는 Play 명령을 실행해보세요.";
    talkViewerBody.appendChild(empty);
    return;
  }
  for (const entry of talkViewerEntries) {
    const row = document.createElement("div");
    row.className = "talk-line";
    if (entry.type === "user") {
      row.classList.add("is-user");
    } else if (entry.type === "system") {
      row.classList.add("is-system");
    } else if (entry.type === "error") {
      row.classList.add("is-error");
    }
    if (entry.provider) {
      row.classList.add(`provider-${entry.provider}`);
    }

    const dot = document.createElement("span");
    dot.className = "talk-line-dot";

    const speaker = document.createElement("span");
    speaker.className = "talk-line-speaker";
    speaker.textContent = entry.speaker;

    const text = document.createElement("span");
    text.className = "talk-line-text";
    text.textContent = entry.text;

    row.appendChild(dot);
    row.appendChild(speaker);
    row.appendChild(text);
    talkViewerBody.appendChild(row);
  }
  if (shouldFollow) {
    talkViewerBody.scrollTop = talkViewerBody.scrollHeight;
  }
}

function initTalkViewer() {
  updateTalkViewerToggleButton();
  renderTalkViewerMeta();
  renderTalkViewer(true);

  if (openTalkViewerBtn) {
    openTalkViewerBtn.addEventListener("click", () => {
      setTalkViewerOpen(!talkViewerOpen);
    });
  }
  if (talkViewerCloseBtn) {
    talkViewerCloseBtn.addEventListener("click", () => {
      setTalkViewerOpen(false);
    });
  }
  if (talkViewerBackdrop) {
    talkViewerBackdrop.addEventListener("click", () => {
      setTalkViewerOpen(false);
    });
  }
  if (talkViewerClearBtn) {
    talkViewerClearBtn.addEventListener("click", () => {
      clearTalkViewer();
    });
  }
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && talkViewerOpen) {
      setTalkViewerOpen(false);
    }
  });
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
    profile.selected_provider = "";
    profile.selected_model = "";
    profile.selected_skill = "";
    profile.selected_project = "";
    profile.selected_role = "executor";
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
  const model = String(session.current_model || "default");
  const project = String(session.current_project || "default");
  const skill = String(session.current_skill || "off");
  const unsafe = formatUnsafeRemaining(session.unsafe_until);
  const runStatus = String(session.run_status || "idle").toLowerCase();
  const rows = [
    { key: "bot", value: profile?.bot_id || "none", extraClass: "" },
    { key: "agent", value: agent, extraClass: `status-chip--agent-${agent}` },
    { key: "model", value: model, extraClass: "" },
    { key: "skill", value: skill, extraClass: "" },
    { key: "project", value: project, extraClass: "" },
    { key: "unsafe", value: unsafe, extraClass: unsafe === "off" ? "" : "status-chip--agent-claude" },
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
  parallelSendBusy = Boolean(busy);
  updateParallelSendButtonState();
  renderSessionProjectControl();
}

function setDebateBusy(busy) {
  debateBusy = Boolean(busy);
  updateParallelSendButtonState();
  renderSessionProjectControl();
}

function setCoworkBusy(busy) {
  coworkBusy = Boolean(busy);
  updateParallelSendButtonState();
  renderSessionProjectControl();
}

function updateParallelSendButtonState() {
  if (!parallelSendBtn) {
    return;
  }
  const disabled = parallelSendBusy || debateBusy || coworkBusy;
  parallelSendBtn.disabled = disabled;
  if (parallelSendBusy) {
    parallelSendBtn.textContent = "병렬 전송 실행 중...";
    return;
  }
  if (debateBusy) {
    parallelSendBtn.textContent = "토론 진행 중...";
    return;
  }
  if (coworkBusy) {
    parallelSendBtn.textContent = "팀워크 진행 중...";
    return;
  }
  parallelSendBtn.textContent = "선택 병렬 전송";
}

function summarizeDebateText(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "(empty)";
  }
  if (text.length <= 160) {
    return text;
  }
  return `${text.slice(0, 160)}...`;
}

function renderDebateList(target, rows, emptyText, detailKey) {
  if (!target) {
    return;
  }
  target.innerHTML = "";
  if (!Array.isArray(rows) || rows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "debate-row";
    empty.textContent = emptyText;
    target.appendChild(empty);
    return;
  }

  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "debate-row";

    const head = document.createElement("div");
    head.className = "debate-row-head";
    const roundNo = Number(row.round_no || 0);
    const label = String(row.speaker_label || row.speaker_bot_id || "bot");
    const status = String(row.status || "unknown");
    head.textContent = `R${roundNo} · ${label} · ${status}`;
    head.classList.add(`debate-row-status-${status}`);

    const detail = document.createElement("div");
    detail.className = "debate-row-detail";
    detail.textContent = summarizeDebateText(row?.[detailKey] || row?.error_text || row?.response_text || status);

    item.appendChild(head);
    item.appendChild(detail);
    target.appendChild(item);
  }
}

function renderDebatePanel(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : null;
  if (!data) {
    if (debateMeta) {
      debateMeta.textContent = "토론이 없습니다.";
    }
    if (debateCurrentTurn) {
      debateCurrentTurn.textContent = "대기 중";
    }
    renderDebateList(debateTurns, [], "턴 로그가 없습니다.", "response_text");
    renderDebateList(debateErrors, [], "오류가 없습니다.", "error_text");
    if (debateStopBtn) {
      debateStopBtn.disabled = true;
    }
    setDebateBusy(false);
    return;
  }

  const debateId = String(data.debate_id || "");
  const topic = String(data.topic || "");
  const status = String(data.status || "unknown");
  const currentTurn = data.current_turn && typeof data.current_turn === "object" ? data.current_turn : null;
  const isActive = status === "queued" || status === "running";

  if (debateMeta) {
    debateMeta.textContent = `ID=${debateId} · ${status.toUpperCase()} · ${topic}`;
  }
  if (debateCurrentTurn) {
    debateCurrentTurn.textContent = currentTurn
      ? `현재 턴: R${Number(currentTurn.round || 0)} / ${String(currentTurn.speaker_label || currentTurn.speaker_bot_id || "bot")}`
      : "현재 턴 없음";
  }
  renderDebateList(debateTurns, Array.isArray(data.turns) ? data.turns : [], "턴 로그가 없습니다.", "response_text");
  renderDebateList(debateErrors, Array.isArray(data.errors) ? data.errors : [], "오류가 없습니다.", "error_text");

  if (debateStopBtn) {
    debateStopBtn.disabled = !isActive || !debateId;
  }
  setDebateBusy(isActive);
}

function summarizeCoworkText(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "(empty)";
  }
  if (text.length <= 180) {
    return text;
  }
  return `${text.slice(0, 180)}...`;
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  if (value < 1024) {
    return `${Math.trunc(value)} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function renderCoworkList(target, rows, emptyText, detailKey, headBuilder) {
  if (!target) {
    return;
  }
  target.innerHTML = "";
  if (!Array.isArray(rows) || rows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "cowork-row";
    empty.textContent = emptyText;
    target.appendChild(empty);
    return;
  }

  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "cowork-row";

    const head = document.createElement("div");
    head.className = "cowork-row-head";
    const status = String(row.status || "unknown");
    head.textContent = headBuilder(row, status);
    head.classList.add(`cowork-row-status-${status}`);

    const detail = document.createElement("div");
    detail.className = "cowork-row-detail";
    detail.textContent = summarizeCoworkText(row?.[detailKey] || row?.error_text || row?.response_text || status);

    item.appendChild(head);
    item.appendChild(detail);
    target.appendChild(item);
  }
}

function renderCoworkArtifacts(payload) {
  if (!coworkArtifacts) {
    return;
  }
  coworkArtifacts.innerHTML = "";
  const files = payload && Array.isArray(payload.files) ? payload.files : [];
  if (!files.length) {
    const empty = document.createElement("div");
    empty.className = "cowork-artifacts-empty";
    empty.textContent = "결과 파일 없음";
    coworkArtifacts.appendChild(empty);
    return;
  }
  const title = document.createElement("div");
  title.className = "cowork-artifacts-title";
  title.textContent = "결과 파일";
  coworkArtifacts.appendChild(title);
  const list = document.createElement("div");
  list.className = "cowork-artifacts-list";
  for (const file of files) {
    const row = document.createElement("div");
    row.className = "cowork-artifact-row";
    const link = document.createElement("a");
    link.className = "cowork-artifact-link";
    link.href = String(file?.url || "#");
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = String(file?.name || "artifact");
    row.appendChild(link);
    const meta = document.createElement("span");
    meta.className = "cowork-artifact-size";
    meta.textContent = formatFileSize(file?.size_bytes);
    row.appendChild(meta);
    list.appendChild(row);
  }
  coworkArtifacts.appendChild(list);
}

function renderCoworkPanel(snapshot) {
  const data = snapshot && typeof snapshot === "object" ? snapshot : null;
  if (!data) {
    if (coworkMeta) {
      coworkMeta.textContent = "팀워크 실행이 없습니다.";
    }
    if (coworkCurrentStage) {
      coworkCurrentStage.textContent = "대기 중";
    }
    renderCoworkList(coworkStages, [], "스테이지 로그가 없습니다.", "response_text", () => "none");
    renderCoworkList(coworkTasks, [], "작업 로그가 없습니다.", "response_text", () => "none");
    renderCoworkList(coworkErrors, [], "오류가 없습니다.", "error_text", () => "none");
    if (coworkFinal) {
      coworkFinal.textContent = "최종 리포트 없음";
    }
    renderCoworkArtifacts(null);
    if (coworkStopBtn) {
      coworkStopBtn.disabled = true;
    }
    setCoworkBusy(false);
    return;
  }

  const coworkId = String(data.cowork_id || "");
  const status = String(data.status || "unknown");
  const task = String(data.task || "");
  const currentStage = String(data.current_stage || "none");
  const currentActor = data.current_actor && typeof data.current_actor === "object" ? data.current_actor : null;
  const isActive = status === "queued" || status === "running";
  const rowsStages = Array.isArray(data.stages) ? data.stages : [];
  const rowsTasks = Array.isArray(data.tasks) ? data.tasks : [];
  const rowsErrors = Array.isArray(data.errors) ? data.errors : [];
  const finalReport = data.final_report && typeof data.final_report === "object" ? data.final_report : null;
  const artifacts = data.artifacts && typeof data.artifacts === "object" ? data.artifacts : null;

  if (coworkMeta) {
    coworkMeta.textContent = `ID=${coworkId} · ${status.toUpperCase()} · ${task}`;
  }
  if (coworkCurrentStage) {
    const actorText = currentActor
      ? `${String(currentActor.label || currentActor.bot_id || "bot")} (${String(currentActor.role || "executor")})`
      : "none";
    coworkCurrentStage.textContent = `현재 단계: ${currentStage} · actor=${actorText}`;
  }

  renderCoworkList(
    coworkStages,
    rowsStages,
    "스테이지 로그가 없습니다.",
    "response_text",
    (row, rowStatus) =>
      `S${Number(row.stage_no || 0)} · ${String(row.stage_type || "stage")} · ${String(
        row.actor_label || row.actor_bot_id || "bot"
      )} · ${rowStatus}`
  );
  renderCoworkList(
    coworkTasks,
    rowsTasks,
    "작업 로그가 없습니다.",
    "response_text",
    (row, rowStatus) =>
      `T${Number(row.task_no || 0)} · ${String(row.assignee_label || row.assignee_bot_id || "bot")} · ${rowStatus}`
  );
  renderCoworkList(
    coworkErrors,
    rowsErrors,
    "오류가 없습니다.",
    "error_text",
    (row, rowStatus) =>
      `${String(row.source || "item")}#${Number(row.source_id || 0)} · ${String(row.label || row.bot_id || "bot")} · ${rowStatus}`
  );

  if (coworkFinal) {
    if (!finalReport) {
      coworkFinal.textContent = "최종 리포트 없음";
    } else {
      coworkFinal.textContent = JSON.stringify(finalReport, null, 2);
    }
  }
  renderCoworkArtifacts(artifacts);
  if (coworkStopBtn) {
    coworkStopBtn.disabled = !isActive || !coworkId;
  }
  setCoworkBusy(isActive);
}

function renderControlTowerPanel(payload) {
  if (!towerMeta || !towerList) {
    return;
  }
  const summary = payload && typeof payload === "object" ? payload.summary : null;
  const rows = payload && typeof payload === "object" && Array.isArray(payload.rows) ? payload.rows : [];
  if (!summary) {
    towerMeta.textContent = "집계 대기 중";
  } else {
    towerMeta.textContent = `healthy=${Number(summary.healthy || 0)} · degraded=${Number(summary.degraded || 0)} · failing=${Number(summary.failing || 0)} · total=${Number(summary.total || rows.length)}`;
  }
  towerList.innerHTML = "";
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "tower-row";
    empty.textContent = "집계된 봇이 없습니다.";
    towerList.appendChild(empty);
    return;
  }
  for (const row of rows) {
    const botId = String(row.bot_id || "");
    const state = String(row.state || "healthy").toLowerCase();
    const reason = String(row.reason || "steady");
    const action = String(row.recommended_action || "none");
    const runStatus = String(row.run_status || "idle");
    const turnTotalRecent = Number(row.turn_total_recent || 0);
    const turnSuccessRateRecent = row.turn_success_rate_recent;
    const item = document.createElement("div");
    item.className = "tower-row";

    const head = document.createElement("div");
    head.className = "tower-row-head";
    const label = document.createElement("span");
    label.textContent = `${String(row.name || botId)} (${botId})`;
    const badge = document.createElement("span");
    badge.className = `tower-row-state state-${state}`;
    badge.textContent = state;
    head.appendChild(label);
    head.appendChild(badge);

    const detail = document.createElement("div");
    detail.className = "tower-row-detail";
    const detailParts = [`reason=${reason}`, `run=${runStatus}`, `action=${action}`];
    if (turnTotalRecent > 0 && Number.isFinite(Number(turnSuccessRateRecent))) {
      detailParts.push(`turns=${turnTotalRecent}`);
      detailParts.push(`success=${Number(turnSuccessRateRecent).toFixed(1)}%`);
    }
    detail.textContent = detailParts.join(" · ");

    item.appendChild(head);
    item.appendChild(detail);

    if (action === "stop_run" || action === "restart_session") {
      const actions = document.createElement("div");
      actions.className = "tower-row-actions";
      const recoverBtn = document.createElement("button");
      recoverBtn.type = "button";
      recoverBtn.className = "tower-recover-btn";
      recoverBtn.textContent = action === "restart_session" ? "복구(/stop+/new)" : "복구(/stop)";
      recoverBtn.dataset.botId = botId;
      recoverBtn.dataset.strategy = action;
      recoverBtn.disabled = towerRecoverBusy;
      actions.appendChild(recoverBtn);
      item.appendChild(actions);
    }

    towerList.appendChild(item);
  }
}

async function refreshControlTower() {
  if (!towerMeta || !towerList) {
    return;
  }
  try {
    const response = await requestJson("/_mock/control_tower");
    renderControlTowerPanel(response?.result || null);
  } catch (error) {
    towerMeta.textContent = `control tower error: ${error.message}`;
  }
}

async function refreshRuntimeProfile() {
  if (!runtimeProfileMeta) {
    return;
  }
  try {
    const response = await requestJson("/_mock/runtime_profile");
    const result = response?.result || {};
    const effective = Number(result.effective_bots || 0);
    const source = Number(result.source_bots || effective);
    const maxBots = result.max_bots == null ? "none" : String(result.max_bots);
    const capped = Boolean(result.is_capped);
    runtimeProfileMeta.textContent = `runtime: effective=${effective}/${source} · max_bots=${maxBots} · capped=${capped ? "yes" : "no"}`;
  } catch (error) {
    runtimeProfileMeta.textContent = `runtime profile error: ${error.message}`;
  }
}

async function recoverControlTowerBot(botId, strategy) {
  if (!botId || towerRecoverBusy) {
    return;
  }
  const profile = uiState.profiles.find((item) => String(item.bot_id || "") === String(botId));
  const fallbackProfile = currentProfile();
  const chatId = profile ? Number(profile.chat_id) : Number(fallbackProfile?.chat_id || chatIdInput.value || 1001);
  const userId = profile ? Number(profile.user_id) : Number(fallbackProfile?.user_id || userIdInput.value || 9001);
  const body = {
    bot_id: String(botId),
    chat_id: Number.isFinite(chatId) ? chatId : 1001,
    user_id: Number.isFinite(userId) ? userId : 9001,
    strategy: String(strategy || "stop_run"),
  };
  if (profile && profile.token) {
    body.token = String(profile.token);
  }
  towerRecoverBusy = true;
  try {
    const response = await requestJson("/_mock/control_tower/recover", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const result = response?.result || {};
    appendBubble(
      "meta",
      `control recover: bot=${result.bot_id || botId} strategy=${result.strategy || strategy} state=${result.state || "unknown"}`
    );
  } catch (error) {
    appendBubble("meta", `control recover error: ${error.message}`);
  } finally {
    towerRecoverBusy = false;
    await refreshControlTower();
    await refresh();
  }
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
    if (botIdInput) {
      botIdInput.value = "";
    }
    tokenInput.value = "";
    chatIdInput.value = "1001";
    userIdInput.value = "9001";
    renderSessionProjectControl();
    return;
  }
  if (botIdInput) {
    botIdInput.value = profile.bot_id || "";
  }
  tokenInput.value = profile.token || "";
  chatIdInput.value = String(numberOrDefault(profile.chat_id, 1001));
  userIdInput.value = String(numberOrDefault(profile.user_id, 9001));
  syncWebhookFormFromProfile(profile);
  renderSessionProjectControl();
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
      const model = String(session.current_model || "");
      const project = String(session.current_project || "");
      const unsafeUntil = String(session.unsafe_until || "");
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
        profile.selected_provider || "",
        profile.selected_model || "",
        profile.selected_skill || "",
        profile.selected_project || "",
        profile.selected_role || "",
        provider,
        model,
        String(session.current_skill || ""),
        project,
        unsafeUntil,
        runStatus,
        healthOk,
      ].join("|");
    })
    .join("||");
}

function isProfileModelApplyBusy(profileId) {
  return profileModelApplyBusy.has(String(profileId || ""));
}

function setProfileModelApplyBusy(profileId, busy) {
  const key = String(profileId || "");
  if (!key) {
    return;
  }
  if (busy) {
    profileModelApplyBusy.add(key);
  } else {
    profileModelApplyBusy.delete(key);
  }
  renderBotList(true);
  renderSessionProjectControl();
}

function renderSessionProjectControl() {
  renderSessionSkillRoleControls();
  if (!sessionProjectSelect) {
    return;
  }
  const profile = currentProfile();
  if (!profile) {
    sessionProjectSelect.innerHTML = '<option value="">default</option>';
    sessionProjectSelect.disabled = true;
    return;
  }
  const diag = profileDiagnostics.get(profile.profile_id) || null;
  const selectedProject = resolveProfileProject(profile, diag);
  const applying = isProfileModelApplyBusy(profile.profile_id);
  const disabled = applying || parallelSendBusy || debateBusy || coworkBusy;

  sessionProjectSelect.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "default";
  defaultOption.selected = !selectedProject;
  sessionProjectSelect.appendChild(defaultOption);

  let matched = false;
  for (const entry of projectCatalog) {
    const option = document.createElement("option");
    option.value = String(entry.path || "");
    option.textContent = String(entry.name || entry.path || "");
    option.selected = option.value === selectedProject;
    if (option.selected) {
      matched = true;
    }
    sessionProjectSelect.appendChild(option);
  }
  if (selectedProject && !matched) {
    const customOption = document.createElement("option");
    customOption.value = selectedProject;
    customOption.textContent = `${selectedProject} (custom)`;
    customOption.selected = true;
    sessionProjectSelect.appendChild(customOption);
  }
  sessionProjectSelect.disabled = disabled;
}

function renderSessionSkillRoleControls() {
  if (!sessionSkillSelect || !sessionRoleSelect) {
    return;
  }
  const profile = currentProfile();
  if (!profile) {
    sessionSkillSelect.innerHTML = '<option value="" disabled>no skills</option>';
    sessionSkillSelect.disabled = true;
    sessionRoleSelect.innerHTML = "";
    for (const roleValue of SUPPORTED_ROLE_OPTIONS) {
      const option = document.createElement("option");
      option.value = roleValue;
      option.textContent = roleValue;
      option.selected = roleValue === "executor";
      sessionRoleSelect.appendChild(option);
    }
    sessionRoleSelect.disabled = true;
    return;
  }

  const diag = profileDiagnostics.get(profile.profile_id) || null;
  const catalogRow = catalogByBotId.get(profile.bot_id);
  const currentSkills = resolveProfileSkills(profile, diag);
  const currentRole = resolveProfileRole(profile, catalogRow);
  const applying = isProfileModelApplyBusy(profile.profile_id);
  const disabled = applying || parallelSendBusy || debateBusy || coworkBusy;

  sessionSkillSelect.innerHTML = "";
  sessionSkillSelect.size = Math.max(2, Math.min(6, skillCatalog.length || 2));
  let matchedSkillCount = 0;
  for (const entry of skillCatalog) {
    const skillId = String(entry?.skill_id || "").trim();
    if (!skillId) {
      continue;
    }
    const option = document.createElement("option");
    option.value = skillId;
    option.textContent = skillId;
    option.selected = currentSkills.includes(skillId);
    if (option.selected) {
      matchedSkillCount += 1;
    }
    sessionSkillSelect.appendChild(option);
  }
  for (const skillId of currentSkills) {
    if (!skillId || Array.from(sessionSkillSelect.options).some((row) => row.value === skillId)) {
      continue;
    }
    const custom = document.createElement("option");
    custom.value = skillId;
    custom.textContent = `${skillId} (custom)`;
    custom.selected = true;
    matchedSkillCount += 1;
    sessionSkillSelect.appendChild(custom);
  }
  if (matchedSkillCount === 0 && sessionSkillSelect.options.length === 0) {
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "no skills";
    placeholder.disabled = true;
    sessionSkillSelect.appendChild(placeholder);
  }
  sessionSkillSelect.disabled = disabled;

  sessionRoleSelect.innerHTML = "";
  for (const roleValue of SUPPORTED_ROLE_OPTIONS) {
    const option = document.createElement("option");
    option.value = roleValue;
    option.textContent = roleValue;
    option.selected = roleValue === currentRole;
    sessionRoleSelect.appendChild(option);
  }
  sessionRoleSelect.disabled = disabled;
}

async function applyProfileProviderAndModel(profile, provider, model) {
  const profileId = String(profile?.profile_id || "");
  if (!profileId || isProfileModelApplyBusy(profileId)) {
    return false;
  }
  const previousProvider = String(profile.selected_provider || "");
  const previousModel = String(profile.selected_model || "");
  setProfileModelApplyBusy(profileId, true);
  try {
    await stopActiveRunBeforeModelApply(profile);

    const modeBaseline = await maxMessageIdForProfile(profile);
    await sendTextToProfile(profile, `/mode ${provider}`);
    const modeOutcome = await waitForCommandOutcome(profile, modeBaseline, "mode", 30);
    if (modeOutcome.status !== "PASS") {
      throw new Error(`provider change failed: ${modeOutcome.detail}`);
    }

    const modelBaseline = await maxMessageIdForProfile(profile);
    await sendTextToProfile(profile, `/model ${model}`);
    const modelOutcome = await waitForCommandOutcome(profile, modelBaseline, "model", 30);
    if (modelOutcome.status !== "PASS") {
      throw new Error(`model change failed: ${modelOutcome.detail}`);
    }

    profile.selected_provider = provider;
    profile.selected_model = model;
    saveState();
    await refresh();
    return true;
  } catch (error) {
    profile.selected_provider = previousProvider;
    profile.selected_model = previousModel;
    saveState();
    appendBubble("meta", `${profile.label}: ${error.message}`);
    await refresh();
    return false;
  } finally {
    setProfileModelApplyBusy(profileId, false);
  }
}

async function applyProfileModelOnly(profile, model) {
  const profileId = String(profile?.profile_id || "");
  if (!profileId || isProfileModelApplyBusy(profileId)) {
    return false;
  }
  const previousModel = String(profile.selected_model || "");
  setProfileModelApplyBusy(profileId, true);
  try {
    await stopActiveRunBeforeModelApply(profile);

    const baseline = await maxMessageIdForProfile(profile);
    await sendTextToProfile(profile, `/model ${model}`);
    const outcome = await waitForCommandOutcome(profile, baseline, "model", 30);
    if (outcome.status !== "PASS") {
      throw new Error(`model change failed: ${outcome.detail}`);
    }
    profile.selected_model = model;
    saveState();
    await refresh();
    return true;
  } catch (error) {
    profile.selected_model = previousModel;
    saveState();
    appendBubble("meta", `${profile.label}: ${error.message}`);
    await refresh();
    return false;
  } finally {
    setProfileModelApplyBusy(profileId, false);
  }
}

async function applyProfileSkill(profile, skillIds) {
  const profileId = String(profile?.profile_id || "");
  if (!profileId || isProfileModelApplyBusy(profileId)) {
    return false;
  }
  const previousSkillIds = normalizeSkillIds(profile.selected_skill);
  const nextSkillIds = normalizeSkillIds(skillIds);
  setProfileModelApplyBusy(profileId, true);
  try {
    await stopActiveRunBeforeModelApply(profile);
    const baseline = await maxMessageIdForProfile(profile);
    const command = nextSkillIds.length > 0 ? `/skill ${nextSkillIds.join(",")}` : "/skill off";
    await sendTextToProfile(profile, command);
    const outcome = await waitForCommandOutcome(profile, baseline, "skill", 30);
    if (outcome.status !== "PASS") {
      throw new Error(`skill change failed: ${outcome.detail}`);
    }
    profile.selected_skill = nextSkillIds.join(",");
    saveState();
    await refresh();
    return true;
  } catch (error) {
    profile.selected_skill = previousSkillIds.join(",");
    saveState();
    appendBubble("meta", `${profile.label}: ${error.message}`);
    await refresh();
    return false;
  } finally {
    setProfileModelApplyBusy(profileId, false);
  }
}

async function stopActiveRunBeforeModelApply(profile) {
  const stopBaseline = await maxMessageIdForProfile(profile);
  await sendTextToProfile(profile, "/stop");
  const stopOutcome = await waitForCommandOutcome(profile, stopBaseline, "stop", 20);
  if (stopOutcome.status !== "PASS") {
    throw new Error(`stop failed: ${stopOutcome.detail}`);
  }
}

async function applyProfileProject(profile, projectPath) {
  const profileId = String(profile?.profile_id || "");
  if (!profileId || isProfileModelApplyBusy(profileId)) {
    return false;
  }
  const previousProject = String(profile.selected_project || "");
  setProfileModelApplyBusy(profileId, true);
  try {
    await stopActiveRunBeforeModelApply(profile);
    const baseline = await maxMessageIdForProfile(profile);
    const command = projectPath ? `/project ${projectPath}` : "/project off";
    await sendTextToProfile(profile, command);
    const outcome = await waitForCommandOutcome(profile, baseline, "project", 30);
    if (outcome.status !== "PASS") {
      throw new Error(`project change failed: ${outcome.detail}`);
    }
    profile.selected_project = String(projectPath || "");
    saveState();
    await refresh();
    return true;
  } catch (error) {
    profile.selected_project = previousProject;
    saveState();
    appendBubble("meta", `${profile.label}: ${error.message}`);
    await refresh();
    return false;
  } finally {
    setProfileModelApplyBusy(profileId, false);
  }
}

async function applyProfileRole(profile, role) {
  const profileId = String(profile?.profile_id || "");
  if (!profileId || isProfileModelApplyBusy(profileId)) {
    return false;
  }
  const previousRole = String(profile.selected_role || "executor");
  const nextRole = normalizeRole(role);
  setProfileModelApplyBusy(profileId, true);
  try {
    const response = await requestJson("/_mock/bot_catalog/role", {
      method: "POST",
      body: JSON.stringify({
        bot_id: String(profile.bot_id || ""),
        role: nextRole,
      }),
    });
    const bot = response?.result?.bot || null;
    profile.selected_role = normalizeRole(bot?.default_role || nextRole);
    await loadCatalog();
    saveState();
    renderBotList(true);
    return true;
  } catch (error) {
    profile.selected_role = previousRole;
    saveState();
    appendBubble("meta", `${profile.label}: role 변경 실패: ${error.message}`);
    renderBotList(true);
    return false;
  } finally {
    setProfileModelApplyBusy(profileId, false);
  }
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
    const provider = resolveProfileProvider(profile, diag, catalogRow);
    const modelOptions = availableModelsForProvider(catalogRow, provider);
    const model = resolveProfileModel(profile, diag, catalogRow, provider);
    const currentSkills = resolveProfileSkills(profile, diag);
    const currentRole = resolveProfileRole(profile, catalogRow);
    const unsafeLabel = formatUnsafeRemaining(session.unsafe_until);
    const applyingModel = isProfileModelApplyBusy(profile.profile_id);
    const controlsDisabled = applyingModel || parallelSendBusy || debateBusy || coworkBusy;
    profile.selected_provider = provider;
    profile.selected_model = model;
    profile.selected_skill = currentSkills.join(",");
    profile.selected_project = resolveProfileProject(profile, diag);
    profile.selected_role = currentRole;

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

    const modelControl = document.createElement("div");
    modelControl.className = "bot-item-model-control";

    const providerLabel = document.createElement("label");
    providerLabel.className = "bot-item-model-label";
    providerLabel.textContent = "Provider";
    const providerSelect = document.createElement("select");
    providerSelect.className = "bot-item-model-select";
    providerSelect.disabled = controlsDisabled;
    providerSelect.addEventListener("click", (event) => event.stopPropagation());
    for (const optionValue of SUPPORTED_PROVIDER_OPTIONS) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionValue;
      option.selected = optionValue === provider;
      providerSelect.appendChild(option);
    }
    providerSelect.addEventListener("change", async (event) => {
      event.stopPropagation();
      const nextProvider = normalizeProvider(providerSelect.value);
      if (!nextProvider || nextProvider === provider) {
        providerSelect.value = provider;
        return;
      }
      const nextModels = availableModelsForProvider(catalogRow, nextProvider);
      const nextDefault = providerDefaultModel(catalogRow, nextProvider);
      const nextModel = nextModels.includes(nextDefault) ? nextDefault : (nextModels[0] || "");
      if (!nextModel) {
        providerSelect.value = provider;
        appendBubble("meta", `${profile.label}: ${nextProvider} 모델 목록이 없습니다.`);
        return;
      }
      const ok = await applyProfileProviderAndModel(profile, nextProvider, nextModel);
      if (!ok) {
        providerSelect.value = provider;
      }
    });
    providerLabel.appendChild(providerSelect);

    const modelLabel = document.createElement("label");
    modelLabel.className = "bot-item-model-label";
    modelLabel.textContent = "Model";
    const modelSelect = document.createElement("select");
    modelSelect.className = "bot-item-model-select";
    modelSelect.disabled = controlsDisabled || modelOptions.length === 0;
    modelSelect.addEventListener("click", (event) => event.stopPropagation());
    for (const modelName of modelOptions) {
      const option = document.createElement("option");
      option.value = modelName;
      option.textContent = modelName;
      option.selected = modelName === model;
      modelSelect.appendChild(option);
    }
    modelSelect.addEventListener("change", async (event) => {
      event.stopPropagation();
      const nextModel = String(modelSelect.value || "").trim();
      if (!nextModel || nextModel === model) {
        modelSelect.value = model;
        return;
      }
      const ok = await applyProfileModelOnly(profile, nextModel);
      if (!ok) {
        modelSelect.value = model;
      }
    });
    modelLabel.appendChild(modelSelect);
    modelControl.appendChild(providerLabel);
    modelControl.appendChild(modelLabel);
    meta.appendChild(modelControl);

    const unsafeRow = document.createElement("div");
    unsafeRow.className = "bot-item-meta-row bot-item-meta-unsafe";
    unsafeRow.textContent = `unsafe: ${unsafeLabel}`;
    if (unsafeLabel !== "off" && unsafeLabel !== "expired") {
      unsafeRow.classList.add("is-active");
    }
    meta.appendChild(unsafeRow);

    item.appendChild(head);
    item.appendChild(meta);
    item.addEventListener("click", () => {
      selectProfile(profile.profile_id);
      refresh();
    });
    botList.appendChild(item);
  }
  updateAddProfileButtonState();
  renderSessionProjectControl();
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

async function loadProjectCatalog() {
  try {
    const response = await requestJson("/_mock/projects");
    const rows = Array.isArray(response?.result?.projects) ? response.result.projects : [];
    projectCatalog = rows
      .map((row) => ({
        name: String(row?.name || row?.path || "").trim(),
        path: String(row?.path || "").trim(),
      }))
      .filter((row) => row.path);
  } catch {
    projectCatalog = [];
  }
  renderSessionProjectControl();
}

async function loadSkillCatalog() {
  try {
    const response = await requestJson("/_mock/skills");
    const rows = Array.isArray(response?.result?.skills) ? response.result.skills : [];
    skillCatalog = rows
      .map((row) => ({
        skill_id: String(row?.skill_id || "").trim(),
        name: String(row?.name || row?.skill_id || "").trim(),
      }))
      .filter((row) => row.skill_id);
  } catch {
    skillCatalog = [];
  }
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
    selected_for_parallel: true,
    selected_provider: normalizeProvider(defaultBot?.default_adapter || "codex"),
    selected_model: "",
    selected_skill: "",
    selected_project: "",
    selected_role: normalizeRole(defaultBot?.default_role || "executor")
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

function reconcileProfilesWithCatalog() {
  if (!Array.isArray(catalog) || catalog.length === 0) {
    return false;
  }

  const knownBotIds = new Set(catalog.map((row) => String(row?.bot_id || "").trim()).filter((value) => value));
  const nextProfiles = [];
  let changed = false;
  const existingProfiles = Array.isArray(uiState.profiles) ? uiState.profiles : [];
  for (const profile of existingProfiles) {
    const currentBotId = String(profile?.bot_id || "").trim();
    if (!currentBotId || !knownBotIds.has(currentBotId)) {
      // Drop stale profile ids that are no longer present in runtime catalog.
      changed = true;
      continue;
    }
    const byBotId = catalogByBotId.get(currentBotId);
    const currentToken = String(profile?.token || "").trim();
    const canonicalToken = String(byBotId?.token || "").trim();
    if (canonicalToken && canonicalToken !== currentToken) {
      profile.token = canonicalToken;
      changed = true;
    }
    if (!profile.selected_provider && byBotId) {
      profile.selected_provider = normalizeProvider(byBotId.default_adapter || "codex");
      changed = true;
    }
    nextProfiles.push(profile);
  }

  const existingByBotId = new Set(nextProfiles.map((profile) => String(profile?.bot_id || "").trim()).filter(Boolean));
  const baseProfile = nextProfiles[0] || existingProfiles[0] || null;
  const defaultChatId = numberOrDefault(baseProfile?.chat_id, 1001);
  const defaultUserId = numberOrDefault(baseProfile?.user_id, 9001);
  for (const row of catalog) {
    const botId = String(row?.bot_id || "").trim();
    if (!botId || existingByBotId.has(botId)) {
      continue;
    }
    nextProfiles.push({
      profile_id: makeProfileId(),
      label: `${String(row?.name || botId)} 기본`,
      bot_id: botId,
      token: String(row?.token || DEFAULT_TOKEN),
      chat_id: defaultChatId,
      user_id: defaultUserId,
      selected_for_parallel: true,
      selected_provider: normalizeProvider(row?.default_adapter || "codex"),
      selected_model: "",
      selected_skill: "",
      selected_project: "",
      selected_role: normalizeRole(row?.default_role || "executor"),
    });
    existingByBotId.add(botId);
    changed = true;
  }

  if (nextProfiles.length !== uiState.profiles.length) {
    changed = true;
  }
  if (changed) {
    uiState.profiles = nextProfiles;
  }

  return changed;
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
  await loadProjectCatalog();
  await loadSkillCatalog();
  reconcileProfilesWithCatalog();
  dedupeProfilesByBotId();
  ensureInitialProfileFromParams();
  ensureSelectedProfile();

  const selected = currentProfile();
  applyProfileToInputs(selected);
  hydrateProfileDialog();
  renderBotList();
  renderParallelResults([]);
  renderDebatePanel(null);
  renderCoworkPanel(null);
  renderControlTowerPanel(null);
  updateParallelSendButtonState();
  saveState();
  if (loadedStateFromLegacy) {
    for (const key of LEGACY_STORAGE_KEYS) {
      localStorage.removeItem(key);
    }
    loadedStateFromLegacy = false;
  }
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
    current_model: null,
    current_project: null,
    unsafe_until: null,
    source: null,
    session_id: null,
    message_id: null
  };
  if (!Array.isArray(messages) || messages.length === 0) {
    return empty;
  }

  let sessionId = null;
  let currentModel = null;
  let currentProject = null;
  let unsafeUntil = null;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    const text = typeof msg?.text === "string" ? msg.text : "";
    if (!sessionId) {
      const sessionMatch = text.match(/(?:^|\n)session=([^\s\n]+)/i);
      if (sessionMatch && sessionMatch[1]) {
        sessionId = sessionMatch[1];
      }
    }
    if (!currentModel) {
      const modelMatch = text.match(/(?:^|\n)model=([^\s\n]+)/i);
      if (modelMatch && modelMatch[1]) {
        const raw = modelMatch[1].trim();
        currentModel = raw.toLowerCase() === "default" ? null : raw;
      }
    }
    if (!currentProject) {
      const projectMatch = text.match(/(?:^|\n)project=([^\n]+)/i);
      if (projectMatch && projectMatch[1]) {
        const raw = projectMatch[1].trim();
        currentProject = /^(default|none|off)$/i.test(raw) ? null : raw;
      }
    }
    if (!unsafeUntil) {
      const unsafeMatch = text.match(/(?:^|\n)unsafe_until=([^\s\n]+)/i);
      if (unsafeMatch && unsafeMatch[1]) {
        const raw = unsafeMatch[1].trim();
        if (/^\d+$/.test(raw)) {
          unsafeUntil = Number(raw);
        }
      }
    }

    const queuedMatch = text.match(/\bagent=(codex|gemini|claude)\b/i);
    if (queuedMatch && queuedMatch[1]) {
      return {
        current_agent: queuedMatch[1].toLowerCase(),
        current_model: currentModel,
        current_project: currentProject,
        unsafe_until: unsafeUntil,
        source: "queued_turn",
        session_id: sessionId,
        message_id: msg.message_id ?? null
      };
    }

    const statusMatch = text.match(/(?:^|\n)adapter=(codex|gemini|claude)\b/i);
    if (statusMatch && statusMatch[1]) {
      return {
        current_agent: statusMatch[1].toLowerCase(),
        current_model: currentModel,
        current_project: currentProject,
        unsafe_until: unsafeUntil,
        source: "status",
        session_id: sessionId,
        message_id: msg.message_id ?? null
      };
    }

    const modeSwitchMatch = text.match(/mode switched:\s*(?:codex|gemini|claude)\s*->\s*(codex|gemini|claude)\b/i);
    if (modeSwitchMatch && modeSwitchMatch[1]) {
      return {
        current_agent: modeSwitchMatch[1].toLowerCase(),
        current_model: currentModel,
        current_project: currentProject,
        unsafe_until: unsafeUntil,
        source: "mode_switch",
        session_id: sessionId,
        message_id: msg.message_id ?? null
      };
    }
  }

  return {
    ...empty,
    session_id: sessionId,
    current_model: currentModel,
    current_project: currentProject,
    unsafe_until: unsafeUntil,
  };
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

function formatAuditTimestamp(value) {
  const ts = Number(value || 0);
  if (!Number.isFinite(ts) || ts <= 0) {
    return "n/a";
  }
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

function renderAuditLogs(logRows, embeddedErrorText = "") {
  if (auditError) {
    auditError.textContent = embeddedErrorText ? `embedded_error: ${embeddedErrorText}` : "";
  }
  if (!auditJson) {
    return;
  }
  const rows = Array.isArray(logRows) ? logRows : [];
  const compact = rows.slice(0, 120).map((row) => ({
    at: formatAuditTimestamp(row?.created_at),
    action: String(row?.action || ""),
    result: String(row?.result || ""),
    chat_id: row?.chat_id ?? null,
    session_id: row?.session_id ?? null,
    detail: String(row?.detail_json || "").slice(0, 280),
  }));
  auditJson.textContent = JSON.stringify(compact, null, 2);
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
    joined.includes("a run is active") ||
    joined.includes("run is already active") ||
    joined.includes("already active in this chat") ||
    joined.includes("use /stop first")
  ) {
    return { done: true, status: "FAIL", detail: "active_run" };
  }
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

function classifyCommandOutcomeFromTexts(texts, commandType) {
  const joined = (texts || []).join("\n");
  const lowered = joined.toLowerCase();
  if (!lowered.trim()) {
    return { done: false, status: "WAIT", detail: "running" };
  }

  if (
    lowered.includes("a run is active") ||
    lowered.includes("use /stop first") ||
    lowered.includes("unsupported provider") ||
    lowered.includes("unsupported model") ||
    lowered.includes("unknown skill") ||
    lowered.includes("no local skills found") ||
    lowered.includes("model name is required") ||
    lowered.includes("no selectable model") ||
    lowered.includes("directory not found") ||
    lowered.includes("not a directory") ||
    lowered.includes("invalid argument") ||
    lowered.includes("access denied")
  ) {
    return { done: true, status: "FAIL", detail: "command_rejected" };
  }

  if (commandType === "mode") {
    if (/\bmode switched:/i.test(joined) || /\bmode unchanged:/i.test(joined)) {
      return { done: true, status: "PASS", detail: "mode_applied" };
    }
  } else if (commandType === "stop") {
    if (
      /\bstop requested\./i.test(joined) ||
      /\bno active run\./i.test(joined) ||
      /\bstopping\.\.\./i.test(joined) ||
      /\bno session yet\./i.test(joined)
    ) {
      return { done: true, status: "PASS", detail: "stop_applied" };
    }
  } else if (commandType === "model") {
    if (/\bmodel updated:/i.test(joined)) {
      return { done: true, status: "PASS", detail: "model_applied" };
    }
  } else if (commandType === "new") {
    if (/\bnew session created:/i.test(joined) || /\bsession reset\./i.test(joined)) {
      return { done: true, status: "PASS", detail: "session_created" };
    }
  } else if (commandType === "project") {
    if (/\bproject updated:/i.test(joined)) {
      return { done: true, status: "PASS", detail: "project_applied" };
    }
  } else if (commandType === "skill") {
    if (/\bskill updated:/i.test(joined) || /(?:^|\n)skill=([^\s\n]+)/i.test(joined)) {
      return { done: true, status: "PASS", detail: "skill_applied" };
    }
  } else if (commandType === "unsafe") {
    if (/\bunsafe updated:/i.test(joined)) {
      return { done: true, status: "PASS", detail: "unsafe_applied" };
    }
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

async function waitForCommandOutcome(profile, baselineMessageId, commandType, timeoutSec = 30) {
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

    const outcome = classifyCommandOutcomeFromTexts(texts, commandType);
    if (outcome.done) {
      return outcome;
    }

    const diagnostics = diagnosticsResp?.result || {};
    const runStatus = String(diagnostics?.session?.run_status || "").toLowerCase();
    if (runStatus === "error") {
      const tag = String(diagnostics?.last_error_tag || "error");
      return { done: true, status: "FAIL", detail: tag };
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return { done: true, status: "FAIL", detail: "timeout" };
}

function escapeRegex(text) {
  return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseRoundOrchestrationCommand(rawText, config) {
  const {
    command,
    subjectKey = "topic",
    subjectLabel = "주제",
    emptyError = "",
    example = "",
    defaultRounds = 2,
    roundsMin = 1,
    roundsMax = 8,
    defaultMaxTurnSec = 90,
    maxTurnMin = 10,
    maxTurnMax = 240,
  } = config || {};

  const cmd = String(command || "").trim().replace(/^\/+/, "");
  if (!cmd) {
    return null;
  }
  const cmdEscaped = escapeRegex(cmd);
  const text = String(rawText || "").trim();
  const commandRe = new RegExp(`^\\/${cmdEscaped}(?:\\s|$)`, "i");
  if (!commandRe.test(text)) {
    return null;
  }

  let rest = text.replace(new RegExp(`^\\/${cmdEscaped}\\b`, "i"), "").trim();
  if (!rest) {
    const sample = example ? ` 예: /${cmd} ${example}` : "";
    return { error: emptyError || `${subjectLabel}를 입력하세요.${sample}` };
  }

  let rounds = Number(defaultRounds);
  let maxTurnSec = Number(defaultMaxTurnSec);
  let freshSession = true;

  const takeIntOption = (name, min, max) => {
    const optionRe = new RegExp(`(?:^|\\s)--${escapeRegex(name)}\\s+(\\d+)(?=\\s|$)`, "i");
    const match = rest.match(optionRe);
    if (!match) {
      return null;
    }
    const value = Number(match[1]);
    rest = rest.replace(match[0], " ").trim();
    if (!Number.isFinite(value) || value < min || value > max) {
      return { error: `--${name} 값은 ${min}~${max} 범위여야 합니다.` };
    }
    return Math.trunc(value);
  };

  const roundsValue = takeIntOption("rounds", Number(roundsMin), Number(roundsMax));
  if (roundsValue && typeof roundsValue === "object" && roundsValue.error) {
    return roundsValue;
  }
  if (typeof roundsValue === "number") {
    rounds = roundsValue;
  }

  const maxTurnValue = takeIntOption("max-turn-sec", Number(maxTurnMin), Number(maxTurnMax));
  if (maxTurnValue && typeof maxTurnValue === "object" && maxTurnValue.error) {
    return maxTurnValue;
  }
  if (typeof maxTurnValue === "number") {
    maxTurnSec = maxTurnValue;
  }

  if (/(?:^|\s)--keep-session(?:\s|$)/i.test(rest)) {
    freshSession = false;
    rest = rest.replace(/(?:^|\s)--keep-session(?=\s|$)/gi, " ").trim();
  }

  const unknownOption = rest.match(/--[A-Za-z0-9_-]+/);
  if (unknownOption) {
    return { error: `알 수 없는 옵션: ${unknownOption[0]}` };
  }

  const subject = rest.replace(/\s+/g, " ").trim();
  if (!subject) {
    return { error: `${subjectLabel}를 입력하세요.` };
  }

  const parsed = {
    rounds,
    max_turn_sec: maxTurnSec,
    fresh_session: freshSession,
  };
  parsed[subjectKey] = subject;
  return parsed;
}

function parseTalkCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "talk",
    subjectKey: "seed",
    subjectLabel: "대화 시작 문장",
    emptyError: "대화 시작 문장을 입력하세요. 예: /talk 오늘 뭐하고 놀까? --rounds 3",
    example: "오늘 뭐하고 놀까? --rounds 3",
    defaultRounds: 3,
    roundsMin: 1,
    roundsMax: 12,
    defaultMaxTurnSec: 60,
    maxTurnMin: 10,
    maxTurnMax: 300,
  });
}

function normalizeTalkReply(rawText) {
  const text = String(rawText || "").replace(/\r\n/g, "\n").trim();
  if (!text) {
    return "";
  }
  const normalized = text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => Boolean(line))
    .join("\n");
  if (!normalized) {
    return "";
  }
  if (normalized.length <= 340) {
    return normalized;
  }
  return `${normalized.slice(0, 340)}...`;
}

function looksLikeControlOnlyText(text) {
  const lowered = String(text || "").toLowerCase();
  if (!lowered.trim()) {
    return true;
  }
  return (
    lowered.includes("turn_completed") ||
    lowered.includes("thread_started") ||
    lowered.includes("turn_started") ||
    lowered.includes("command_started") ||
    lowered.includes("command_completed") ||
    lowered.includes("bridge_status") ||
    lowered.includes("new session created:") ||
    lowered.includes("stop requested.") ||
    lowered.includes("no active run.")
  );
}

function extractTalkReplyFromTexts(texts) {
  const rows = Array.isArray(texts) ? texts : [];
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const chunk = String(rows[i] || "");
    const lines = chunk.split(/\r?\n/);
    for (let j = lines.length - 1; j >= 0; j -= 1) {
      const line = lines[j];
      const eventMatch = line.match(EVENT_LINE_RE);
      if (!eventMatch) {
        continue;
      }
      const eventType = String(eventMatch[3] || "").toLowerCase();
      const detail = normalizeTalkReply(eventMatch[4] || "");
      if (eventType === "assistant_message" && detail) {
        return detail;
      }
    }
  }

  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const chunk = String(rows[i] || "");
    const cleaned = chunk
      .split(/\r?\n/)
      .map((line) => {
        const eventMatch = line.match(EVENT_LINE_RE);
        if (!eventMatch) {
          return line.trim();
        }
        const eventType = String(eventMatch[3] || "").toLowerCase();
        if (eventType !== "assistant_message") {
          return "";
        }
        return String(eventMatch[4] || "").trim();
      })
      .filter((line) => Boolean(line))
      .join("\n");
    const normalized = normalizeTalkReply(cleaned);
    if (normalized && !looksLikeControlOnlyText(normalized)) {
      return normalized;
    }
  }
  return "";
}

function talkSpeakerLabel(profile, index) {
  const label = String(profile?.label || "").trim();
  if (label) {
    return label;
  }
  const botId = String(profile?.bot_id || "").trim();
  if (botId) {
    return botId;
  }
  return `bot-${index + 1}`;
}

function buildTalkPrompt({ speakerLabel, seed, transcript, roundNo, turnNo, totalTurns }) {
  const historyLines = (Array.isArray(transcript) ? transcript : [])
    .slice(-12)
    .map((entry) => {
      const speaker = String(entry?.speaker || "unknown").trim() || "unknown";
      const text = normalizeTalkReply(entry?.text || "");
      return text ? `${speaker}: ${text}` : "";
    })
    .filter((line) => Boolean(line));

  return [
    "[Talk Mode]",
    `너는 멀티봇 자유 대화 참가자 "${speakerLabel}"이다.`,
    "아래 대화를 보고 다음 한 마디를 자연스럽게 이어서 답해라.",
    "규칙:",
    "- 한국어로 답변",
    "- 1~3문장, 과도한 설명/코드/마크다운 금지",
    "- 이름 prefix를 붙이지 말고 내용만 출력",
    `사용자 시작 문장: ${seed}`,
    `현재 턴: ${turnNo}/${totalTurns} (round=${roundNo})`,
    "",
    "[대화 기록]",
    ...historyLines.map((line) => `- ${line}`),
    "",
    "지금 바로 다음 답장을 출력해라.",
  ].join("\n");
}

function formatTalkFailure(detail) {
  const normalized = String(detail || "").toLowerCase();
  if (!normalized || normalized === "error") {
    return "[응답 실패]";
  }
  if (normalized === "timeout") {
    return "[응답 시간 초과]";
  }
  if (normalized === "active_run") {
    return "[기존 실행이 남아 있어 응답 실패]";
  }
  return `[응답 실패: ${normalized}]`;
}

async function waitForTalkOutcome(profile, baselineMessageId, timeoutSec = 60) {
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
      return {
        done: true,
        status: outcome.status,
        detail: outcome.detail,
        reply: extractTalkReplyFromTexts(texts),
      };
    }

    const diagnostics = diagnosticsResp?.result || {};
    const runStatus = String(diagnostics?.session?.run_status || "").toLowerCase();
    if (texts.length > 0 && runStatus === "completed") {
      return {
        done: true,
        status: "PASS",
        detail: "run_status=completed",
        reply: extractTalkReplyFromTexts(texts),
      };
    }
    if (runStatus === "error") {
      const tag = String(diagnostics?.last_error_tag || "error");
      return { done: true, status: "FAIL", detail: tag, reply: extractTalkReplyFromTexts(texts) };
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return { done: true, status: "FAIL", detail: "timeout", reply: "" };
}

function parseDebateCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "debate",
    subjectKey: "topic",
    subjectLabel: "토론 주제",
    emptyError: "토론 주제를 입력하세요. 예: /debate AI가 개발자를 대체할까?",
    example: "AI가 개발자를 대체할까?",
    defaultRounds: 3,
    roundsMin: 1,
    roundsMax: 10,
    defaultMaxTurnSec: 90,
    maxTurnMin: 10,
    maxTurnMax: 300,
  });
}

function parseRelayCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "relay",
    subjectKey: "topic",
    subjectLabel: "릴레이 주제",
    emptyError: "릴레이 주제를 입력하세요. 예: /relay 퇴근길 지하철에서 생긴 일",
    example: "퇴근길 지하철에서 생긴 일",
    defaultRounds: 3,
  });
}

function parsePitchbattleCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "pitchbattle",
    subjectKey: "topic",
    subjectLabel: "피치 배틀 주제",
    emptyError: "피치 배틀 주제를 입력하세요. 예: /pitchbattle 주말 사이드 프로젝트 아이디어",
    example: "주말 사이드 프로젝트 아이디어",
    defaultRounds: 2,
  });
}

function parseQuizbattleCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "quizbattle",
    subjectKey: "topic",
    subjectLabel: "퀴즈 배틀 주제",
    emptyError: "퀴즈 배틀 주제를 입력하세요. 예: /quizbattle 한국사 상식",
    example: "한국사 상식",
    defaultRounds: 2,
  });
}

function parseDebateLiteCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "debate-lite",
    subjectKey: "topic",
    subjectLabel: "토론 주제",
    emptyError: "경량 토론 주제를 입력하세요. 예: /debate-lite 원격근무 vs 오피스근무",
    example: "원격근무 vs 오피스근무",
    defaultRounds: 2,
  });
}

function parseImprovCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "improv",
    subjectKey: "topic",
    subjectLabel: "즉흥극 상황",
    emptyError: "즉흥극 상황을 입력하세요. 예: /improv 우주 엘리베이터에서 길을 잃은 팀",
    example: "우주 엘리베이터에서 길을 잃은 팀",
    defaultRounds: 3,
  });
}

function parseQuestCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "quest",
    subjectKey: "topic",
    subjectLabel: "퀘스트 미션",
    emptyError: "퀘스트 미션을 입력하세요. 예: /quest 30분 내 랜딩 페이지 초안 완성",
    example: "30분 내 랜딩 페이지 초안 완성",
    defaultRounds: 3,
  });
}

function parseMemechainCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "memechain",
    subjectKey: "topic",
    subjectLabel: "밈 체인 주제",
    emptyError: "밈 체인 주제를 입력하세요. 예: /memechain 재택근무 현실",
    example: "재택근무 현실",
    defaultRounds: 3,
  });
}

function parseCourtCommand(rawText) {
  return parseRoundOrchestrationCommand(rawText, {
    command: "court",
    subjectKey: "topic",
    subjectLabel: "사건 주제",
    emptyError: "법정극 사건을 입력하세요. 예: /court 버그 배포 사고 책임 공방",
    example: "버그 배포 사고 책임 공방",
    defaultRounds: 2,
  });
}

function parsePlayCommand(rawText) {
  const parserByKey = {
    relay: parseRelayCommand,
    pitchbattle: parsePitchbattleCommand,
    quizbattle: parseQuizbattleCommand,
    "debate-lite": parseDebateLiteCommand,
    improv: parseImprovCommand,
    quest: parseQuestCommand,
    memechain: parseMemechainCommand,
    court: parseCourtCommand,
  };
  for (const kind of PLAY_COMMAND_KEYS) {
    const parser = parserByKey[kind];
    if (typeof parser !== "function") {
      continue;
    }
    const parsed = parser(rawText);
    if (parsed !== null) {
      return { kind, parsed };
    }
  }
  return null;
}

function parseOrchestrationCommand(rawText) {
  const talkCommand = parseTalkCommand(rawText);
  if (talkCommand !== null) {
    return { kind: "talk", parsed: talkCommand };
  }
  const debateCommand = parseDebateCommand(rawText);
  if (debateCommand !== null) {
    return { kind: "debate", parsed: debateCommand };
  }
  const coworkCommand = parseCoworkCommand(rawText);
  if (coworkCommand !== null) {
    return { kind: "cowork", parsed: coworkCommand };
  }
  const playCommand = parsePlayCommand(rawText);
  if (playCommand !== null) {
    return playCommand;
  }
  return null;
}

function parseCoworkCommand(rawText) {
  const text = String(rawText || "").trim();
  if (!/^\/cowork(?:\s|$)/i.test(text)) {
    return null;
  }

  let rest = text.replace(/^\/cowork\b/i, "").trim();
  if (!rest) {
    return { error: "작업 요청을 입력하세요. 예: /cowork 대시보드 API 성능 개선" };
  }

  let maxParallel = 3;
  let maxTurnSec = 90;
  let freshSession = true;
  let keepPartialOnError = true;

  const takeIntOption = (name, min, max) => {
    const optionRe = new RegExp(`(?:^|\\s)--${name}\\s+(\\d+)(?=\\s|$)`, "i");
    const match = rest.match(optionRe);
    if (!match) {
      return null;
    }
    const value = Number(match[1]);
    rest = rest.replace(match[0], " ").trim();
    if (!Number.isFinite(value) || value < min || value > max) {
      return { error: `--${name} 값은 ${min}~${max} 범위여야 합니다.` };
    }
    return value;
  };

  const maxParallelValue = takeIntOption("max-parallel", 1, 8);
  if (maxParallelValue && typeof maxParallelValue === "object" && maxParallelValue.error) {
    return maxParallelValue;
  }
  if (typeof maxParallelValue === "number") {
    maxParallel = Math.trunc(maxParallelValue);
  }

  const maxTurnValue = takeIntOption("max-turn-sec", 10, 300);
  if (maxTurnValue && typeof maxTurnValue === "object" && maxTurnValue.error) {
    return maxTurnValue;
  }
  if (typeof maxTurnValue === "number") {
    maxTurnSec = Math.trunc(maxTurnValue);
  }

  if (/(?:^|\s)--keep-session(?:\s|$)/i.test(rest)) {
    freshSession = false;
    rest = rest.replace(/(?:^|\s)--keep-session(?=\s|$)/gi, " ").trim();
  }
  if (/(?:^|\s)--strict(?:\s|$)/i.test(rest)) {
    keepPartialOnError = false;
    rest = rest.replace(/(?:^|\s)--strict(?=\s|$)/gi, " ").trim();
  }

  const unknownOption = rest.match(/--[A-Za-z0-9_-]+/);
  if (unknownOption) {
    return { error: `알 수 없는 옵션: ${unknownOption[0]}` };
  }

  const task = rest.replace(/\s+/g, " ").trim();
  if (!task) {
    return { error: "작업 요청을 입력하세요." };
  }
  return {
    task,
    max_parallel: maxParallel,
    max_turn_sec: maxTurnSec,
    fresh_session: freshSession,
    keep_partial_on_error: keepPartialOnError,
  };
}

function isDebateTerminalStatus(status) {
  return status === "completed" || status === "stopped" || status === "failed";
}

function isCoworkTerminalStatus(status) {
  return status === "completed" || status === "stopped" || status === "failed";
}

function buildDebateScopeKeyFromProfiles(profiles) {
  const rows = Array.isArray(profiles) ? profiles : [];
  const keys = rows
    .map((profile) => {
      const botId = String(profile?.bot_id || "").trim();
      const chatId = Number(profile?.chat_id);
      if (!botId || !Number.isFinite(chatId)) {
        return "";
      }
      return `${botId}:${Math.trunc(chatId)}`;
    })
    .filter((value) => value.length > 0)
    .sort();
  if (keys.length < 2) {
    return null;
  }
  return keys.join("|");
}

function stopDebatePolling() {
  if (debatePollingTimer) {
    clearInterval(debatePollingTimer);
    debatePollingTimer = null;
  }
}

function stopCoworkPolling() {
  if (coworkPollingTimer) {
    clearInterval(coworkPollingTimer);
    coworkPollingTimer = null;
  }
}

async function pollDebateStatus(debateId) {
  const id = String(debateId || "").trim();
  if (!id) {
    stopDebatePolling();
    renderDebatePanel(null);
    uiState.active_debate_id = null;
    uiState.active_debate_scope_key = null;
    saveState();
    return;
  }

  try {
    const response = await requestJson(`/_mock/debate/${encodeURIComponent(id)}`);
    const snapshot = response?.result || null;
    if (!snapshot) {
      return;
    }
    const status = String(snapshot.status || "unknown");
    renderDebatePanel(snapshot);
    if (status !== debateLastStatus) {
      debateLastStatus = status;
      if (isDebateTerminalStatus(status)) {
        appendBubble("meta", `토론 ${status}: ${String(snapshot.topic || "")}`);
      }
    }

    if (isDebateTerminalStatus(status)) {
      stopDebatePolling();
      uiState.active_debate_id = null;
      uiState.active_debate_scope_key = null;
    } else {
      uiState.active_debate_id = String(snapshot.debate_id || id);
      const scopeKey = String(snapshot.scope_key || "").trim();
      uiState.active_debate_scope_key = scopeKey || uiState.active_debate_scope_key || null;
    }
    saveState();
  } catch (error) {
    if (String(error?.message || "").includes("404")) {
      stopDebatePolling();
      renderDebatePanel(null);
      uiState.active_debate_id = null;
      uiState.active_debate_scope_key = null;
      saveState();
      return;
    }
    appendBubble("meta", `debate poll error: ${error.message}`);
  }
}

async function pollCoworkStatus(coworkId) {
  const id = String(coworkId || "").trim();
  if (!id) {
    stopCoworkPolling();
    renderCoworkPanel(null);
    uiState.active_cowork_id = null;
    saveState();
    return;
  }

  try {
    const response = await requestJson(`/_mock/cowork/${encodeURIComponent(id)}`);
    const snapshot = response?.result || null;
    if (!snapshot) {
      return;
    }
    const status = String(snapshot.status || "unknown");
    renderCoworkPanel(snapshot);
    if (status !== coworkLastStatus) {
      coworkLastStatus = status;
      if (isCoworkTerminalStatus(status)) {
        const files = snapshot?.artifacts?.files;
        const firstUrl = Array.isArray(files) && files[0] && typeof files[0].url === "string" ? files[0].url : "";
        const artifactNote = firstUrl ? ` · 결과: ${firstUrl}` : "";
        appendBubble("meta", `팀워크 ${status}: ${String(snapshot.task || "")}${artifactNote}`);
      }
    }

    if (isCoworkTerminalStatus(status)) {
      stopCoworkPolling();
      uiState.active_cowork_id = null;
    } else {
      uiState.active_cowork_id = String(snapshot.cowork_id || id);
    }
    saveState();
  } catch (error) {
    if (String(error?.message || "").includes("404")) {
      stopCoworkPolling();
      renderCoworkPanel(null);
      uiState.active_cowork_id = null;
      saveState();
      return;
    }
    appendBubble("meta", `cowork poll error: ${error.message}`);
  }
}

function startDebatePolling(debateId) {
  stopDebatePolling();
  const id = String(debateId || "").trim();
  if (!id) {
    return;
  }
  void pollDebateStatus(id);
  debatePollingTimer = setInterval(() => {
    void pollDebateStatus(id);
  }, 1000);
}

function startCoworkPolling(coworkId) {
  stopCoworkPolling();
  const id = String(coworkId || "").trim();
  if (!id) {
    return;
  }
  void pollCoworkStatus(id);
  coworkPollingTimer = setInterval(() => {
    void pollCoworkStatus(id);
  }, 1000);
}

async function recoverActiveDebate() {
  try {
    const selectedScope = buildDebateScopeKeyFromProfiles(
      uiState.profiles.filter((profile) => profile.selected_for_parallel !== false)
    );
    const storedScope = String(uiState.active_debate_scope_key || "").trim();
    const scopeKey = selectedScope || storedScope || null;
    const activeUrl = scopeKey
      ? `/_mock/debate/active?scope_key=${encodeURIComponent(scopeKey)}`
      : "/_mock/debate/active";
    const active = await requestJson(activeUrl);
    const snapshot = active?.result || null;
    if (!snapshot || !snapshot.debate_id) {
      uiState.active_debate_id = null;
      uiState.active_debate_scope_key = scopeKey;
      saveState();
      renderDebatePanel(null);
      return;
    }
    uiState.active_debate_id = String(snapshot.debate_id);
    uiState.active_debate_scope_key = String(snapshot.scope_key || scopeKey || "").trim() || null;
    saveState();
    renderDebatePanel(snapshot);
    if (isDebateTerminalStatus(String(snapshot.status || ""))) {
      return;
    }
    startDebatePolling(snapshot.debate_id);
  } catch {
    renderDebatePanel(null);
  }
}

async function recoverActiveCowork() {
  try {
    const active = await requestJson("/_mock/cowork/active");
    const snapshot = active?.result || null;
    if (!snapshot || !snapshot.cowork_id) {
      uiState.active_cowork_id = null;
      saveState();
      renderCoworkPanel(null);
      return;
    }
    uiState.active_cowork_id = String(snapshot.cowork_id);
    saveState();
    renderCoworkPanel(snapshot);
    if (isCoworkTerminalStatus(String(snapshot.status || ""))) {
      return;
    }
    startCoworkPolling(snapshot.cowork_id);
  } catch {
    renderCoworkPanel(null);
  }
}

async function runDebateFlow(targets, parsedCommand) {
  if (!parsedCommand || parsedCommand.error) {
    const detail = parsedCommand?.error || "토론 명령 파싱 실패";
    renderParallelResults([{ label: "토론", status: "FAIL", detail }]);
    appendBubble("meta", detail);
    return;
  }
  if (debateBusy) {
    renderParallelResults([{ label: "토론", status: "FAIL", detail: "이미 진행 중인 토론이 있습니다." }]);
    appendBubble("meta", "이미 진행 중인 토론이 있습니다.");
    return;
  }
  if (coworkBusy) {
    renderParallelResults([{ label: "토론", status: "FAIL", detail: "팀워크 실행 중에는 토론을 시작할 수 없습니다." }]);
    appendBubble("meta", "팀워크 실행 중에는 토론을 시작할 수 없습니다.");
    return;
  }

  const payload = {
    topic: parsedCommand.topic,
    rounds: parsedCommand.rounds,
    max_turn_sec: parsedCommand.max_turn_sec,
    fresh_session: parsedCommand.fresh_session,
    profiles: targets.map((profile) => ({
      profile_id: String(profile.profile_id),
      label: String(profile.label || profile.bot_id || "Bot"),
      bot_id: String(profile.bot_id || ""),
      token: String(profile.token || ""),
      chat_id: Number(profile.chat_id),
      user_id: Number(profile.user_id)
    }))
  };
  const scopeKey = buildDebateScopeKeyFromProfiles(payload.profiles);

  try {
    const response = await requestJson("/_mock/debate/start", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    const snapshot = response?.result || null;
    renderParallelResults([{ label: "토론", status: "PASS", detail: "started" }]);
    renderDebatePanel(snapshot);
    const debateId = String(snapshot?.debate_id || "");
    uiState.active_debate_id = debateId || null;
    uiState.active_debate_scope_key = String(snapshot?.scope_key || scopeKey || "").trim() || null;
    debateLastStatus = String(snapshot?.status || "");
    saveState();
    if (debateId) {
      startDebatePolling(debateId);
    }
    appendBubble("meta", `토론 시작: ${payload.topic}`);
  } catch (error) {
    renderParallelResults([{ label: "토론", status: "FAIL", detail: String(error.message || error) }]);
    appendBubble("meta", `토론 시작 실패: ${error.message}`);
  }
}

async function runCoworkFlow(targets, parsedCommand) {
  if (!parsedCommand || parsedCommand.error) {
    const detail = parsedCommand?.error || "팀워크 명령 파싱 실패";
    renderParallelResults([{ label: "팀워크", status: "FAIL", detail }]);
    appendBubble("meta", detail);
    return;
  }
  if (coworkBusy) {
    renderParallelResults([{ label: "팀워크", status: "FAIL", detail: "이미 진행 중인 팀워크가 있습니다." }]);
    appendBubble("meta", "이미 진행 중인 팀워크가 있습니다.");
    return;
  }
  if (debateBusy) {
    renderParallelResults([{ label: "팀워크", status: "FAIL", detail: "토론 진행 중에는 팀워크를 시작할 수 없습니다." }]);
    appendBubble("meta", "토론 진행 중에는 팀워크를 시작할 수 없습니다.");
    return;
  }

  const payload = {
    task: parsedCommand.task,
    max_parallel: parsedCommand.max_parallel,
    max_turn_sec: parsedCommand.max_turn_sec,
    fresh_session: parsedCommand.fresh_session,
    keep_partial_on_error: parsedCommand.keep_partial_on_error,
    profiles: targets.map((profile) => ({
      profile_id: String(profile.profile_id),
      label: String(profile.label || profile.bot_id || "Bot"),
      bot_id: String(profile.bot_id || ""),
      token: String(profile.token || ""),
      chat_id: Number(profile.chat_id),
      user_id: Number(profile.user_id),
      role: normalizeRole(profile.selected_role || catalogByBotId.get(profile.bot_id)?.default_role || "executor"),
    })),
  };

  try {
    const response = await requestJson("/_mock/cowork/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const snapshot = response?.result || null;
    renderParallelResults([{ label: "팀워크", status: "PASS", detail: "started" }]);
    renderCoworkPanel(snapshot);
    const coworkId = String(snapshot?.cowork_id || "");
    uiState.active_cowork_id = coworkId || null;
    coworkLastStatus = String(snapshot?.status || "");
    saveState();
    if (coworkId) {
      startCoworkPolling(coworkId);
    }
    appendBubble("meta", `팀워크 시작: ${payload.task}`);
  } catch (error) {
    renderParallelResults([{ label: "팀워크", status: "FAIL", detail: String(error.message || error) }]);
    appendBubble("meta", `팀워크 시작 실패: ${error.message}`);
  }
}

async function runTalkFlow(targets, parsedCommand) {
  if (!parsedCommand || parsedCommand.error) {
    const detail = parsedCommand?.error || "talk 명령 파싱 실패";
    renderParallelResults([{ label: "talk", status: "FAIL", detail }]);
    appendBubble("meta", detail);
    return;
  }
  if (debateBusy) {
    renderParallelResults([{ label: "talk", status: "FAIL", detail: "토론 진행 중에는 talk를 시작할 수 없습니다." }]);
    appendBubble("meta", "토론 진행 중에는 talk를 시작할 수 없습니다.");
    return;
  }
  if (coworkBusy) {
    renderParallelResults([{ label: "talk", status: "FAIL", detail: "팀워크 실행 중에는 talk를 시작할 수 없습니다." }]);
    appendBubble("meta", "팀워크 실행 중에는 talk를 시작할 수 없습니다.");
    return;
  }

  const rows = [];
  const updateRows = () => renderParallelResults(rows.slice(-180));
  const addRow = (label, status, detail) => {
    rows.push({ label, status, detail });
    updateRows();
    return rows.length - 1;
  };
  const setRow = (index, status, detail) => {
    if (index < 0 || index >= rows.length) {
      return;
    }
    rows[index] = { ...rows[index], status, detail };
    updateRows();
  };

  const transcript = [{ speaker: "User", text: parsedCommand.seed }];
  let passCount = 0;
  let failCount = 0;
  const totalTurns = parsedCommand.rounds * targets.length;
  const speakerMeta = new Map(
    targets.map((profile, index) => {
      const speaker = talkSpeakerLabel(profile, index);
      const diagnostics = profileDiagnostics.get(profile.profile_id) || null;
      const catalogRow = catalogByBotId.get(profile.bot_id);
      const provider = resolveProfileProvider(profile, diagnostics, catalogRow);
      return [speaker, { provider }];
    })
  );

  clearTalkViewer();
  setTalkViewerSession({
    status: "running",
    mode: "talk",
    title: "Talk",
    seed: parsedCommand.seed,
    rounds: parsedCommand.rounds,
    participants: targets.length,
    passCount: 0,
    failCount: 0,
    verdict: "-",
  });
  appendTalkViewerEntry({ type: "user", speaker: "User", text: parsedCommand.seed });
  setTalkViewerOpen(true);
  addRow("User", "PASS", parsedCommand.seed);
  setParallelSendBusy(true);
  appendBubble("meta", `talk 시작: rounds=${parsedCommand.rounds}, participants=${targets.length}`);

  try {
    if (parsedCommand.fresh_session) {
      for (const [index, profile] of targets.entries()) {
        const speaker = talkSpeakerLabel(profile, index);
        const preparingRow = addRow(speaker, "WAIT", "session 준비 중...");
        try {
          await stopActiveRunBeforeModelApply(profile);
        } catch {
          // no-op: stop 실패는 다음 /new 시도에서 다시 판단한다.
        }
        const baseline = await maxMessageIdForProfile(profile);
        await sendTextToProfile(profile, "/new");
        const newOutcome = await waitForCommandOutcome(profile, baseline, "new", 25);
        if (newOutcome.status === "PASS") {
          setRow(preparingRow, "PASS", "new session");
          appendTalkViewerEntry({ type: "system", speaker: "System", text: `${speaker} session 준비 완료` });
        } else {
          setRow(preparingRow, "FAIL", `new session 실패: ${newOutcome.detail}`);
          appendTalkViewerEntry({
            type: "error",
            speaker: "System",
            text: `${speaker} session 준비 실패: ${newOutcome.detail}`,
          });
        }
      }
    }

    for (let roundNo = 1; roundNo <= parsedCommand.rounds; roundNo += 1) {
      for (let idx = 0; idx < targets.length; idx += 1) {
        const profile = targets[idx];
        const speaker = talkSpeakerLabel(profile, idx);
        const turnNo = ((roundNo - 1) * targets.length) + idx + 1;
        const rowIndex = addRow(`R${roundNo} ${speaker}`, "WAIT", "thinking...");
        const prompt = buildTalkPrompt({
          speakerLabel: speaker,
          seed: parsedCommand.seed,
          transcript,
          roundNo,
          turnNo,
          totalTurns,
        });

        try {
          let baseline = await maxMessageIdForProfile(profile);
          await sendTextToProfile(profile, prompt);
          let outcome = await waitForTalkOutcome(profile, baseline, parsedCommand.max_turn_sec);
          if (outcome.status === "FAIL" && outcome.detail === "active_run") {
            setRow(rowIndex, "WAIT", "active run 감지, /stop 후 재시도...");
            await stopActiveRunBeforeModelApply(profile);
            baseline = await maxMessageIdForProfile(profile);
            await sendTextToProfile(profile, prompt);
            outcome = await waitForTalkOutcome(profile, baseline, parsedCommand.max_turn_sec);
          }

          if (outcome.status === "PASS") {
            const reply = normalizeTalkReply(outcome.reply || "") || "(응답 본문 없음)";
            transcript.push({ speaker, text: reply });
            passCount += 1;
            setRow(rowIndex, "PASS", reply);
            appendTalkViewerEntry({
              type: "bot",
              speaker,
              text: reply,
              provider: speakerMeta.get(speaker)?.provider || "",
            });
          } else {
            const failure = formatTalkFailure(outcome.detail);
            transcript.push({ speaker, text: failure });
            failCount += 1;
            setRow(rowIndex, "FAIL", failure);
            appendTalkViewerEntry({
              type: "error",
              speaker,
              text: failure,
              provider: speakerMeta.get(speaker)?.provider || "",
            });
          }
          setTalkViewerSession({
            passCount,
            failCount,
          });
        } catch (error) {
          const failure = `[응답 실패: ${String(error?.message || error)}]`;
          transcript.push({ speaker, text: failure });
          failCount += 1;
          setRow(rowIndex, "FAIL", failure);
          appendTalkViewerEntry({
            type: "error",
            speaker,
            text: failure,
            provider: speakerMeta.get(speaker)?.provider || "",
          });
          setTalkViewerSession({
            passCount,
            failCount,
          });
        }
      }
    }
    addRow("talk", failCount > 0 ? "FAIL" : "PASS", `completed · pass=${passCount} fail=${failCount}`);
    appendTalkViewerEntry({
      type: "system",
      speaker: "System",
      text: `talk 완료 · pass=${passCount} · fail=${failCount}`,
    });
    setTalkViewerSession({
      status: failCount > 0 ? "failed" : "completed",
      passCount,
      failCount,
      verdict: "-",
    });
    appendBubble("meta", `talk 완료: pass=${passCount}, fail=${failCount}`);
    await refresh();
  } catch (error) {
    const detail = String(error?.message || error);
    addRow("talk", "FAIL", detail);
    appendTalkViewerEntry({
      type: "error",
      speaker: "System",
      text: `talk 중단: ${detail}`,
    });
    setTalkViewerSession({
      status: "failed",
      passCount,
      failCount,
      verdict: "-",
    });
    appendBubble("meta", `talk 실행 실패: ${detail}`);
  } finally {
    setParallelSendBusy(false);
  }
}

const PLAY_MODE_SPECS = Object.freeze({
  relay: {
    key: "relay",
    labelKo: "릴레이",
    viewerTitle: "Relay",
    minParticipants: 2,
    hasVerdict: false,
    scenarioRule: "이전 발화를 자연스럽게 이어서 짧은 다음 장면을 만든다.",
  },
  pitchbattle: {
    key: "pitchbattle",
    labelKo: "피치 배틀",
    viewerTitle: "Pitch Battle",
    minParticipants: 2,
    hasVerdict: true,
    scenarioRule: "각자 핵심 가치와 실행 가능성을 강조해 피치한다.",
  },
  quizbattle: {
    key: "quizbattle",
    labelKo: "퀴즈 배틀",
    viewerTitle: "Quiz Battle",
    minParticipants: 2,
    hasVerdict: true,
    scenarioRule: "한 줄 문제/답변 흐름으로 짧고 명확하게 진행한다.",
  },
  "debate-lite": {
    key: "debate-lite",
    labelKo: "경량 토론",
    viewerTitle: "Debate Lite",
    minParticipants: 2,
    hasVerdict: true,
    scenarioRule: "찬반 논지를 짧게 제시하고 근거를 한 개 이상 포함한다.",
  },
  improv: {
    key: "improv",
    labelKo: "즉흥극",
    viewerTitle: "Improv",
    minParticipants: 2,
    hasVerdict: false,
    scenarioRule: "캐릭터 몰입을 유지하면서 상황을 전진시킨다.",
  },
  quest: {
    key: "quest",
    labelKo: "퀘스트",
    viewerTitle: "Quest",
    minParticipants: 2,
    hasVerdict: true,
    scenarioRule: "협동 미션 진행 상태를 짧게 보고하고 다음 액션을 제시한다.",
  },
  memechain: {
    key: "memechain",
    labelKo: "밈 체인",
    viewerTitle: "Meme Chain",
    minParticipants: 2,
    hasVerdict: false,
    scenarioRule: "한 줄 밈/드립으로 리듬 있게 이어간다.",
  },
  court: {
    key: "court",
    labelKo: "법정극",
    viewerTitle: "Court",
    minParticipants: 3,
    hasVerdict: true,
    scenarioRule: "검사/변호/증인 관점처럼 역할 분담된 논리를 유지한다.",
  },
});

function playModeSpec(modeKey) {
  return PLAY_MODE_SPECS[String(modeKey || "").trim().toLowerCase()] || null;
}

function buildPlayPrompt({ modeSpec, speakerLabel, topic, transcript, roundNo, turnNo, totalTurns }) {
  const historyLines = (Array.isArray(transcript) ? transcript : [])
    .slice(-12)
    .map((entry) => {
      const speaker = String(entry?.speaker || "unknown").trim() || "unknown";
      const text = normalizeTalkReply(entry?.text || "");
      return text ? `${speaker}: ${text}` : "";
    })
    .filter((line) => Boolean(line));

  return [
    `[${modeSpec.viewerTitle}]`,
    `너는 "${speakerLabel}" 참가자다.`,
    `주제: ${topic}`,
    `룰: ${modeSpec.scenarioRule}`,
    "출력 규칙:",
    "- 한국어, 1~3문장",
    "- 이름 prefix/마크다운/코드블록 금지",
    `현재 턴: ${turnNo}/${totalTurns} (round=${roundNo})`,
    "",
    "[대화 기록]",
    ...historyLines.map((line) => `- ${line}`),
    "",
    "지금 바로 다음 발화만 출력해라.",
  ].join("\n");
}

function buildPlayVerdictPrompt({ modeSpec, judgeLabel, topic, transcript }) {
  const historyLines = (Array.isArray(transcript) ? transcript : [])
    .slice(-18)
    .map((entry) => {
      const speaker = String(entry?.speaker || "unknown").trim() || "unknown";
      const text = normalizeTalkReply(entry?.text || "");
      return text ? `${speaker}: ${text}` : "";
    })
    .filter((line) => Boolean(line));

  let verdictRule = "반드시 첫 줄에 WINNER: <speaker> 형식으로 출력하고 다음 줄에 VERDICT: <한 줄 사유>를 출력하라.";
  if (modeSpec.key === "quest") {
    verdictRule = "반드시 첫 줄에 RESULT: SUCCESS 또는 RESULT: FAIL 중 하나만 출력하고 다음 줄에 VERDICT: <한 줄 사유>를 출력하라.";
  } else if (modeSpec.key === "court") {
    verdictRule = "반드시 첫 줄에 VERDICT: <유죄|무죄|기각 등> 형식으로 출력하고 다음 줄에 WINNER: <speaker 또는 side>를 출력하라.";
  }

  return [
    `[${modeSpec.viewerTitle} Verdict]`,
    `너는 최종 판정자 "${judgeLabel}"다.`,
    `주제: ${topic}`,
    verdictRule,
    "출력은 최대 2~3줄로 간결하게 유지한다.",
    "",
    "[기록]",
    ...historyLines.map((line) => `- ${line}`),
    "",
    "지금 최종 판정을 출력해라.",
  ].join("\n");
}

function extractPlayVerdictFromReply(modeKey, rawText) {
  const text = normalizeTalkReply(rawText || "");
  if (!text) {
    return "";
  }
  const resultMatch = text.match(/(?:^|\n)\s*RESULT\s*:\s*(SUCCESS|FAIL)\b/i);
  const winnerMatch = text.match(/(?:^|\n)\s*WINNER\s*:\s*([^\n]+)/i);
  const verdictMatch = text.match(/(?:^|\n)\s*VERDICT\s*:\s*([^\n]+)/i);
  const mode = String(modeKey || "").trim().toLowerCase();

  if (mode === "quest" && resultMatch) {
    return `RESULT: ${String(resultMatch[1]).toUpperCase()}`;
  }
  if (mode === "court") {
    if (verdictMatch) {
      return `VERDICT: ${String(verdictMatch[1]).trim()}`;
    }
    if (winnerMatch) {
      return `WINNER: ${String(winnerMatch[1]).trim()}`;
    }
    if (resultMatch) {
      return `RESULT: ${String(resultMatch[1]).toUpperCase()}`;
    }
    return "";
  }
  if (winnerMatch) {
    return `WINNER: ${String(winnerMatch[1]).trim()}`;
  }
  if (verdictMatch) {
    return `VERDICT: ${String(verdictMatch[1]).trim()}`;
  }
  if (resultMatch) {
    return `RESULT: ${String(resultMatch[1]).toUpperCase()}`;
  }
  return "";
}

function buildTalkSpeakerMeta(targets) {
  return new Map(
    (Array.isArray(targets) ? targets : []).map((profile, index) => {
      const speaker = talkSpeakerLabel(profile, index);
      const diagnostics = profileDiagnostics.get(profile.profile_id) || null;
      const catalogRow = catalogByBotId.get(profile.bot_id);
      const provider = resolveProfileProvider(profile, diagnostics, catalogRow);
      return [speaker, { provider }];
    })
  );
}

async function runPlayTurn(profile, prompt, maxTurnSec, rowLabel, speakerMeta) {
  const rowSpeaker = String(rowLabel || "")
    .replace(/^R\d+\s+/i, "")
    .replace(/^Judge\s+/i, "")
    .trim();
  const speaker = rowSpeaker || String(profile?.label || profile?.bot_id || "bot");
  const provider = speakerMeta instanceof Map ? String(speakerMeta.get(speaker)?.provider || "") : "";

  try {
    let baseline = await maxMessageIdForProfile(profile);
    await sendTextToProfile(profile, prompt);
    let outcome = await waitForTalkOutcome(profile, baseline, maxTurnSec);
    if (outcome.status === "FAIL" && outcome.detail === "active_run") {
      await stopActiveRunBeforeModelApply(profile);
      baseline = await maxMessageIdForProfile(profile);
      await sendTextToProfile(profile, prompt);
      outcome = await waitForTalkOutcome(profile, baseline, maxTurnSec);
    }
    if (outcome.status === "PASS") {
      const reply = normalizeTalkReply(outcome.reply || "") || "(응답 본문 없음)";
      return { status: "PASS", speaker, provider, reply, detail: reply };
    }
    const failure = formatTalkFailure(outcome.detail);
    return { status: "FAIL", speaker, provider, reply: failure, detail: failure };
  } catch (error) {
    const failure = `[응답 실패: ${String(error?.message || error)}]`;
    return { status: "FAIL", speaker, provider, reply: failure, detail: failure };
  }
}

async function prepareFreshSessionsIfNeeded(targets, freshSession, modeLabel, addRow, setRow) {
  if (!freshSession) {
    return;
  }
  for (const [index, profile] of targets.entries()) {
    const speaker = talkSpeakerLabel(profile, index);
    const preparingRow = addRow(speaker, "WAIT", "session 준비 중...");
    try {
      await stopActiveRunBeforeModelApply(profile);
    } catch {
      // no-op: stop 실패는 다음 /new 시도에서 다시 판단한다.
    }
    const baseline = await maxMessageIdForProfile(profile);
    await sendTextToProfile(profile, "/new");
    const newOutcome = await waitForCommandOutcome(profile, baseline, "new", 25);
    if (newOutcome.status === "PASS") {
      setRow(preparingRow, "PASS", "new session");
      appendTalkViewerEntry({ type: "system", speaker: "System", text: `${speaker} session 준비 완료 (${modeLabel})` });
    } else {
      setRow(preparingRow, "FAIL", `new session 실패: ${newOutcome.detail}`);
      appendTalkViewerEntry({
        type: "error",
        speaker: "System",
        text: `${speaker} session 준비 실패: ${newOutcome.detail}`,
      });
    }
  }
}

function finalizePlayFlow(modeSpec, addRow, passCount, failCount, verdict) {
  const hasVerdict = Boolean(modeSpec?.hasVerdict);
  const verdictText = hasVerdict ? String(verdict || "[판정 실패]") : "-";
  const summaryDetail = hasVerdict
    ? `completed · pass=${passCount} fail=${failCount} · verdict=${verdictText}`
    : `completed · pass=${passCount} fail=${failCount}`;
  addRow(modeSpec.key, failCount > 0 ? "FAIL" : "PASS", summaryDetail);
  appendTalkViewerEntry({
    type: "system",
    speaker: "System",
    text: hasVerdict
      ? `${modeSpec.viewerTitle} 완료 · pass=${passCount} · fail=${failCount} · ${verdictText}`
      : `${modeSpec.viewerTitle} 완료 · pass=${passCount} · fail=${failCount}`,
  });
  setTalkViewerSession({
    status: failCount > 0 ? "failed" : "completed",
    passCount,
    failCount,
    verdict: verdictText,
  });
  appendBubble("meta", hasVerdict
    ? `${modeSpec.labelKo} 완료: pass=${passCount}, fail=${failCount}, verdict=${verdictText}`
    : `${modeSpec.labelKo} 완료: pass=${passCount}, fail=${failCount}`);
}

async function runPlayFlow(targets, parsedCommand, modeKey) {
  const modeSpec = playModeSpec(modeKey);
  if (!modeSpec) {
    renderParallelResults([{ label: "play", status: "FAIL", detail: `unknown mode: ${String(modeKey || "")}` }]);
    appendBubble("meta", `unknown play mode: ${String(modeKey || "")}`);
    return;
  }
  if (!parsedCommand || parsedCommand.error) {
    const detail = parsedCommand?.error || `${modeSpec.labelKo} 명령 파싱 실패`;
    renderParallelResults([{ label: modeSpec.key, status: "FAIL", detail }]);
    appendBubble("meta", detail);
    return;
  }
  if (targets.length < Number(modeSpec.minParticipants || 2)) {
    const detail = `${modeSpec.labelKo}는 ${modeSpec.minParticipants}개 이상의 봇 선택이 필요합니다.`;
    renderParallelResults([{ label: modeSpec.key, status: "FAIL", detail }]);
    appendBubble("meta", detail);
    return;
  }
  if (debateBusy) {
    const detail = "토론 진행 중에는 Play 명령을 시작할 수 없습니다.";
    renderParallelResults([{ label: modeSpec.key, status: "FAIL", detail }]);
    appendBubble("meta", detail);
    return;
  }
  if (coworkBusy) {
    const detail = "팀워크 실행 중에는 Play 명령을 시작할 수 없습니다.";
    renderParallelResults([{ label: modeSpec.key, status: "FAIL", detail }]);
    appendBubble("meta", detail);
    return;
  }

  const rows = [];
  const updateRows = () => renderParallelResults(rows.slice(-180));
  const addRow = (label, status, detail) => {
    rows.push({ label, status, detail });
    updateRows();
    return rows.length - 1;
  };
  const setRow = (index, status, detail) => {
    if (index < 0 || index >= rows.length) {
      return;
    }
    rows[index] = { ...rows[index], status, detail };
    updateRows();
  };

  const topic = String(parsedCommand.topic || "").trim();
  const transcript = [{ speaker: "User", text: topic }];
  const speakerMeta = buildTalkSpeakerMeta(targets);
  let passCount = 0;
  let failCount = 0;
  let verdict = modeSpec.hasVerdict ? "[판정 실패]" : "-";
  const totalTurns = (Number(parsedCommand.rounds) * targets.length) + (modeSpec.hasVerdict ? 1 : 0);

  clearTalkViewer();
  setTalkViewerSession({
    status: "running",
    mode: modeSpec.key,
    title: modeSpec.viewerTitle,
    seed: topic,
    rounds: Number(parsedCommand.rounds || 0),
    participants: targets.length,
    passCount: 0,
    failCount: 0,
    verdict: modeSpec.hasVerdict ? "pending" : "-",
  });
  appendTalkViewerEntry({ type: "user", speaker: "User", text: topic });
  setTalkViewerOpen(true);
  addRow("User", "PASS", topic);
  setParallelSendBusy(true);
  appendBubble("meta", `${modeSpec.labelKo} 시작: rounds=${parsedCommand.rounds}, participants=${targets.length}`);

  try {
    await prepareFreshSessionsIfNeeded(targets, Boolean(parsedCommand.fresh_session), modeSpec.viewerTitle, addRow, setRow);

    for (let roundNo = 1; roundNo <= Number(parsedCommand.rounds || 0); roundNo += 1) {
      for (let idx = 0; idx < targets.length; idx += 1) {
        const profile = targets[idx];
        const speaker = talkSpeakerLabel(profile, idx);
        const turnNo = ((roundNo - 1) * targets.length) + idx + 1;
        const rowLabel = `R${roundNo} ${speaker}`;
        const rowIndex = addRow(rowLabel, "WAIT", "thinking...");
        const prompt = buildPlayPrompt({
          modeSpec,
          speakerLabel: speaker,
          topic,
          transcript,
          roundNo,
          turnNo,
          totalTurns,
        });
        const turn = await runPlayTurn(profile, prompt, Number(parsedCommand.max_turn_sec || 90), rowLabel, speakerMeta);
        if (turn.status === "PASS") {
          passCount += 1;
          transcript.push({ speaker, text: turn.reply });
          setRow(rowIndex, "PASS", turn.detail);
          appendTalkViewerEntry({
            type: "bot",
            speaker,
            text: turn.reply,
            provider: turn.provider,
          });
        } else {
          failCount += 1;
          transcript.push({ speaker, text: turn.reply });
          setRow(rowIndex, "FAIL", turn.detail);
          appendTalkViewerEntry({
            type: "error",
            speaker,
            text: turn.reply,
            provider: turn.provider,
          });
        }
        setTalkViewerSession({ passCount, failCount });
      }
    }

    if (modeSpec.hasVerdict) {
      const judge = targets[0];
      const judgeSpeaker = talkSpeakerLabel(judge, 0);
      const judgeRowLabel = `Judge ${judgeSpeaker}`;
      const rowIndex = addRow(judgeRowLabel, "WAIT", "verdict...");
      const verdictPrompt = buildPlayVerdictPrompt({
        modeSpec,
        judgeLabel: judgeSpeaker,
        topic,
        transcript,
      });
      const turn = await runPlayTurn(
        judge,
        verdictPrompt,
        Number(parsedCommand.max_turn_sec || 90),
        judgeRowLabel,
        speakerMeta
      );
      if (turn.status === "PASS") {
        passCount += 1;
        transcript.push({ speaker: judgeSpeaker, text: turn.reply });
        setRow(rowIndex, "PASS", turn.reply);
        appendTalkViewerEntry({
          type: "bot",
          speaker: judgeSpeaker,
          text: turn.reply,
          provider: turn.provider,
        });
        const extractedVerdict = extractPlayVerdictFromReply(modeSpec.key, turn.reply);
        if (extractedVerdict) {
          verdict = extractedVerdict;
          addRow("verdict", "PASS", verdict);
        } else {
          verdict = "[판정 실패]";
          addRow("verdict", "PASS", verdict);
          appendTalkViewerEntry({
            type: "system",
            speaker: "System",
            text: "판정 파싱 실패: 형식(WINNER/VERDICT/RESULT)을 찾지 못했습니다.",
          });
        }
      } else {
        failCount += 1;
        setRow(rowIndex, "FAIL", turn.reply);
        appendTalkViewerEntry({
          type: "error",
          speaker: judgeSpeaker,
          text: turn.reply,
          provider: turn.provider,
        });
        verdict = "[판정 실패]";
        addRow("verdict", "PASS", verdict);
      }
      setTalkViewerSession({ passCount, failCount, verdict });
    }

    finalizePlayFlow(modeSpec, addRow, passCount, failCount, verdict);
    await refresh();
  } catch (error) {
    const detail = String(error?.message || error);
    addRow(modeSpec.key, "FAIL", detail);
    appendTalkViewerEntry({
      type: "error",
      speaker: "System",
      text: `${modeSpec.viewerTitle} 중단: ${detail}`,
    });
    setTalkViewerSession({
      status: "failed",
      passCount,
      failCount,
      verdict: modeSpec.hasVerdict ? verdict : "-",
    });
    appendBubble("meta", `${modeSpec.labelKo} 실행 실패: ${detail}`);
  } finally {
    setParallelSendBusy(false);
  }
}

async function runRelayFlow(targets, parsedCommand) {
  await runPlayFlow(targets, parsedCommand, "relay");
}

async function runPitchbattleFlow(targets, parsedCommand) {
  await runPlayFlow(targets, parsedCommand, "pitchbattle");
}

async function runQuizbattleFlow(targets, parsedCommand) {
  await runPlayFlow(targets, parsedCommand, "quizbattle");
}

async function runDebateLiteFlow(targets, parsedCommand) {
  await runPlayFlow(targets, parsedCommand, "debate-lite");
}

async function runImprovFlow(targets, parsedCommand) {
  await runPlayFlow(targets, parsedCommand, "improv");
}

async function runQuestFlow(targets, parsedCommand) {
  await runPlayFlow(targets, parsedCommand, "quest");
}

async function runMemechainFlow(targets, parsedCommand) {
  await runPlayFlow(targets, parsedCommand, "memechain");
}

async function runCourtFlow(targets, parsedCommand) {
  await runPlayFlow(targets, parsedCommand, "court");
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

  const orchestration = parseOrchestrationCommand(text);
  if (orchestration !== null) {
    if (orchestration.kind === "talk") {
      await runTalkFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "debate") {
      await runDebateFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "cowork") {
      await runCoworkFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "relay") {
      await runRelayFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "pitchbattle") {
      await runPitchbattleFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "quizbattle") {
      await runQuizbattleFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "debate-lite") {
      await runDebateLiteFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "improv") {
      await runImprovFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "quest") {
      await runQuestFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "memechain") {
      await runMemechainFlow(targets, orchestration.parsed);
      return;
    }
    if (orchestration.kind === "court") {
      await runCourtFlow(targets, orchestration.parsed);
      return;
    }
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
          let outcome = await waitForParallelOutcome(profile, baseline, 60);
          if (outcome.status === "FAIL" && outcome.detail === "active_run") {
            appendBubble("meta", `${profile.label}: active run 감지, /stop 후 재시도합니다.`);
            await stopActiveRunBeforeModelApply(profile);
            const retryBaseline = await maxMessageIdForProfile(profile);
            await sendTextToProfile(profile, text);
            const retry = await waitForParallelOutcome(profile, retryBaseline, 60);
            if (retry.status === "PASS") {
              outcome = { done: true, status: "PASS", detail: "retry_after_stop" };
            } else {
              outcome = retry;
            }
          }
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
    if (!catalogByBotId.has(String(profile.bot_id || ""))) {
      profileDiagnostics.set(profile.profile_id, {
        health: { bot: { ok: false, error: "unknown bot_id in current catalog" } },
        session: { current_agent: "unknown", run_status: "unknown" },
        metrics: { in_flight_runs: null, worker_heartbeat: { run_worker: null, update_worker: null } },
        last_error_tag: "unknown",
        threads_top10: []
      });
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
  await refreshControlTower();
}

async function refreshOnce() {
  let profile = currentProfile();
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
    renderAuditLogs([], "");
    return;
  }

  if (!catalogByBotId.has(String(profile.bot_id || ""))) {
    await loadCatalog();
    const changed = reconcileProfilesWithCatalog();
    if (changed) {
      dedupeProfilesByBotId();
      ensureSelectedProfile();
      profile = currentProfile();
      applyProfileToInputs(profile);
      saveState();
      renderBotList();
      appendBubble("meta", "bot catalog 갱신으로 프로필을 카탈로그와 동기화했습니다.");
    }
  }

  profile = currentProfile();
  if (!profile || !profile.token) {
    return;
  }

  try {
    const knownBot = catalogByBotId.has(String(profile.bot_id || ""));
    const [messagesResp, stateResp, threadsResp, diagnosticsResp, auditResp] = await Promise.all([
      requestJson(`/_mock/messages?token=${encodeURIComponent(profile.token)}&chat_id=${Number(profile.chat_id)}&limit=120`),
      requestJson(`/_mock/state?token=${encodeURIComponent(profile.token)}`),
      requestJson(`/_mock/threads?token=${encodeURIComponent(profile.token)}`),
      knownBot
        ? requestJson(
            `/_mock/bot_diagnostics?bot_id=${encodeURIComponent(profile.bot_id)}&token=${encodeURIComponent(
              profile.token
            )}&chat_id=${Number(profile.chat_id)}&limit=120`
          )
        : Promise.resolve({
            result: {
              health: { bot: { ok: false, error: "unknown bot_id in current catalog" } },
              session: { current_agent: "unknown", run_status: "unknown" },
              metrics: { in_flight_runs: null, worker_heartbeat: { run_worker: null, update_worker: null } },
              last_error_tag: "unknown",
              threads_top10: []
            }
          }),
      knownBot
        ? requestJson(
            `/_mock/audit_logs?bot_id=${encodeURIComponent(profile.bot_id)}&chat_id=${Number(profile.chat_id)}&limit=120`
          )
        : Promise.resolve({ result: { logs: [], embedded_error: `unknown bot_id: ${profile.bot_id}` } }),
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
    renderAuditLogs(auditResp?.result?.logs || [], String(auditResp?.result?.embedded_error || ""));

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

  if (parseOrchestrationCommand(text) !== null) {
    if (parallelMessageInput && !parallelMessageInput.value.trim()) {
      parallelMessageInput.value = text;
    }
    await runParallelSend();
    messageInput.value = "";
    hideCommandSuggest();
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
  const adapter = String(currentCatalogRow?.default_adapter || "codex");

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
    selected_provider: normalizeProvider(created.default_adapter || "codex"),
    selected_model: "",
    selected_skill: "",
    selected_project: "",
    selected_role: normalizeRole(created.default_role || "executor"),
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
    selected_for_parallel: true,
    selected_provider: normalizeProvider(row?.default_adapter || "codex"),
    selected_model: "",
    selected_skill: "",
    selected_project: "",
    selected_role: normalizeRole(row?.default_role || "executor")
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

if (debateStopBtn) {
  debateStopBtn.addEventListener("click", async () => {
    const debateId = String(uiState.active_debate_id || "").trim();
    if (!debateId) {
      return;
    }
    try {
      await requestJson(`/_mock/debate/${encodeURIComponent(debateId)}/stop`, { method: "POST" });
      appendBubble("meta", "토론 중단 요청을 전송했습니다.");
      await pollDebateStatus(debateId);
    } catch (error) {
      appendBubble("meta", `토론 중단 실패: ${error.message}`);
    }
  });
}

if (coworkStopBtn) {
  coworkStopBtn.addEventListener("click", async () => {
    const coworkId = String(uiState.active_cowork_id || "").trim();
    if (!coworkId) {
      return;
    }
    try {
      await requestJson(`/_mock/cowork/${encodeURIComponent(coworkId)}/stop`, { method: "POST" });
      appendBubble("meta", "팀워크 중단 요청을 전송했습니다.");
      await pollCoworkStatus(coworkId);
    } catch (error) {
      appendBubble("meta", `팀워크 중단 실패: ${error.message}`);
    }
  });
}

if (towerRefreshBtn) {
  towerRefreshBtn.addEventListener("click", () => {
    void refreshControlTower();
  });
}

if (towerList) {
  towerList.addEventListener("click", (event) => {
    const target = event.target.closest("button[data-bot-id][data-strategy]");
    if (!target) {
      return;
    }
    const botId = String(target.dataset.botId || "");
    const strategy = String(target.dataset.strategy || "stop_run");
    void recoverControlTowerBot(botId, strategy);
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

if (sessionProjectSelect) {
  sessionProjectSelect.addEventListener("change", async () => {
    const profile = currentProfile();
    if (!profile) {
      renderSessionProjectControl();
      return;
    }
    const currentValue = resolveProfileProject(profile, profileDiagnostics.get(profile.profile_id) || null);
    const nextValue = normalizeProjectPath(sessionProjectSelect.value);
    if (nextValue === currentValue) {
      return;
    }
    const ok = await applyProfileProject(profile, nextValue);
    if (!ok) {
      renderSessionProjectControl();
    }
  });
}

if (sessionSkillSelect) {
  sessionSkillSelect.addEventListener("change", async () => {
    const profile = currentProfile();
    if (!profile) {
      renderSessionProjectControl();
      return;
    }
    const diag = profileDiagnostics.get(profile.profile_id) || null;
    const currentSkills = resolveProfileSkills(profile, diag);
    const nextSkills = normalizeSkillIds(
      Array.from(sessionSkillSelect.selectedOptions).map((option) => String(option.value || ""))
    );
    if (nextSkills.join(",") === currentSkills.join(",")) {
      return;
    }
    const ok = await applyProfileSkill(profile, nextSkills);
    if (!ok) {
      renderSessionProjectControl();
    }
  });
}

if (sessionRoleSelect) {
  sessionRoleSelect.addEventListener("change", async () => {
    const profile = currentProfile();
    if (!profile) {
      renderSessionProjectControl();
      return;
    }
    const catalogRow = catalogByBotId.get(profile.bot_id);
    const currentRole = resolveProfileRole(profile, catalogRow);
    const nextRole = normalizeRole(sessionRoleSelect.value);
    if (!nextRole || nextRole === currentRole) {
      sessionRoleSelect.value = currentRole;
      return;
    }
    const ok = await applyProfileRole(profile, nextRole);
    if (!ok) {
      renderSessionProjectControl();
    }
  });
}

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
initSessionAccordions();
initSectionToggles();
initParallelResultsToggle();
initDebatePanelToggle();
initCoworkPanelToggle();
initTowerPanelToggle();
initTalkViewer();
hydrateInputs().then(async () => {
  updateEssentialToggleButton();
  await recoverActiveDebate();
  await recoverActiveCowork();
  await refreshRuntimeProfile();
  await refreshControlTower();
  await refreshProfileDiagnostics();
  await refresh();
});
