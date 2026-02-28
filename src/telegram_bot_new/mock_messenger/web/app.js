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
const stateJson = document.getElementById("state-json");
const threadsJson = document.getElementById("threads-json");

const refreshStateBtn = document.getElementById("refresh-state-btn");
const toggleEssentialBtn = document.getElementById("toggle-essential-btn");
const sendBtn = document.getElementById("send-btn");
const setWebhookBtn = document.getElementById("set-webhook-btn");
const deleteWebhookBtn = document.getElementById("delete-webhook-btn");
const rateLimitBtn = document.getElementById("rate-limit-btn");

const rateMethodInput = document.getElementById("rate-method-input");
const rateCountInput = document.getElementById("rate-count-input");
const rateRetryInput = document.getElementById("rate-retry-input");

const DEFAULT_TOKEN = "mock_token_1";
const STORAGE_KEY = "mock_messenger_ui_state";
const SCROLL_BOTTOM_THRESHOLD = 24;
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
let essentialMode = true;
let latestMessages = [];
let commandSuggestItems = [];
let commandSuggestActiveIndex = -1;

function tokenValue() {
  return tokenInput.value.trim();
}

function chatIdValue() {
  return Number(chatIdInput.value || 0);
}

function userIdValue() {
  return Number(userIdInput.value || 0);
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

function numberOrDefault(value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) {
    return fallback;
  }
  return Math.trunc(parsed);
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveState() {
  const state = {
    token: tokenValue(),
    chat_id: chatIdValue(),
    user_id: userIdValue(),
    webhook_url: webhookUrlInput.value.trim(),
    webhook_secret: webhookSecretInput.value.trim()
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

async function hydrateInputs() {
  const params = new URLSearchParams(window.location.search);
  const saved = loadState();

  const paramToken = (params.get("token") || "").trim();
  const paramChatId = params.get("chat_id");
  const paramUserId = params.get("user_id");

  tokenInput.value = paramToken || saved.token || tokenInput.value.trim() || DEFAULT_TOKEN;
  chatIdInput.value = String(numberOrDefault(paramChatId ?? saved.chat_id ?? chatIdInput.value, 1001));
  userIdInput.value = String(numberOrDefault(paramUserId ?? saved.user_id ?? userIdInput.value, 9001));
  webhookUrlInput.value = (params.get("webhook_url") || saved.webhook_url || webhookUrlInput.value || "").trim();
  webhookSecretInput.value = (params.get("webhook_secret") || saved.webhook_secret || webhookSecretInput.value || "").trim();

  if (!paramToken) {
    try {
      const stateResp = await requestJson("/_mock/state");
      const bots = stateResp?.result?.state?.bots;
      if (Array.isArray(bots) && bots.length > 0) {
        const current = tokenValue();
        const hasCurrent = bots.some((bot) => bot.token === current);
        if (!hasCurrent) {
          tokenInput.value = bots[0].token;
        }
      }
    } catch {
      // keep local/default token when mock state fetch fails
    }
  }
  saveState();
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

    const element = /** @type {Element} */ (node);
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

function maskToken(token) {
  if (!token || typeof token !== "string") {
    return "";
  }
  if (token.length <= 10) {
    return token;
  }
  return `${token.slice(0, 4)}...${token.slice(-4)}`;
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

async function refresh() {
  const token = tokenValue();

  try {
    if (!token) {
      const [stateResp, threadsResp] = await Promise.all([
        requestJson("/_mock/state"),
        requestJson("/_mock/threads")
      ]);
      lastTimelineSignature = "";
      latestMessages = [];
      renderTimeline([]);
      if (agentJson) {
        agentJson.textContent = JSON.stringify(inferCurrentAgent([]), null, 2);
      }
      stateJson.textContent = JSON.stringify(compactState(stateResp.result), null, 2);
      threadsJson.textContent = JSON.stringify(compactThreads(threadsResp.result, chatIdValue()), null, 2);
      return;
    }

    const [messagesResp, stateResp, threadsResp] = await Promise.all([
      requestJson(`/_mock/messages?token=${encodeURIComponent(token)}&chat_id=${chatIdValue()}&limit=100`),
      requestJson(`/_mock/state?token=${encodeURIComponent(token)}`),
      requestJson(`/_mock/threads?token=${encodeURIComponent(token)}`)
    ]);

    latestMessages = Array.isArray(messagesResp.result.messages) ? messagesResp.result.messages : [];
    renderTimeline(latestMessages);

    if (agentJson) {
      agentJson.textContent = JSON.stringify(inferCurrentAgent(latestMessages), null, 2);
    }
    stateJson.textContent = JSON.stringify(compactState(stateResp.result), null, 2);
    threadsJson.textContent = JSON.stringify(compactThreads(threadsResp.result, chatIdValue()), null, 2);
  } catch (error) {
    appendBubble("meta", `refresh error: ${error.message}`);
  }
}

function updateEssentialToggleButton() {
  if (!toggleEssentialBtn) {
    return;
  }
  const modeLabel = essentialMode ? "ON" : "OFF";
  toggleEssentialBtn.textContent = `필수 메시지 보기: ${modeLabel}`;
  toggleEssentialBtn.classList.toggle("is-active", essentialMode);
}

sendBtn.addEventListener("click", async () => {
  const token = tokenValue();
  const text = messageInput.value.trim();
  if (!token) {
    appendBubble("meta", `token is required (default: ${DEFAULT_TOKEN})`);
    return;
  }
  if (!text) {
    appendBubble("meta", "message is required");
    return;
  }

  try {
    followTimeline = true;
    await requestJson("/_mock/send", {
      method: "POST",
      body: JSON.stringify({
        token,
        chat_id: chatIdValue(),
        user_id: userIdValue(),
        text
      })
    });
    messageInput.value = "";
    hideCommandSuggest();
    saveState();
    await refresh();
  } catch (error) {
    appendBubble("meta", `send error: ${error.message}`);
  }
});

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
    saveState();
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
    saveState();
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

tokenInput.addEventListener("change", saveState);
chatIdInput.addEventListener("change", saveState);
userIdInput.addEventListener("change", saveState);
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

setInterval(refresh, 1000);
hydrateInputs().then(() => {
  updateEssentialToggleButton();
  return refresh();
});
