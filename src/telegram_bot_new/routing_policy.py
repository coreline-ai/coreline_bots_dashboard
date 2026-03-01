from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from telegram_bot_new.model_presets import resolve_provider_default_model

AUTO_ROUTE_RE = re.compile(r"^\s*@auto(?::(?P<provider>codex|gemini|claude))?\s+", re.IGNORECASE)

CODE_HINTS = (
    "code",
    "coding",
    "debug",
    "bug",
    "fix",
    "implement",
    "refactor",
    "test",
    "pytest",
    "typescript",
    "javascript",
    "python",
    "sql",
    "api",
    "function",
    "함수",
    "구현",
    "버그",
    "디버그",
    "테스트",
    "리팩토링",
)

ANALYSIS_HINTS = (
    "analysis",
    "analyze",
    "architecture",
    "design",
    "strategy",
    "review",
    "compare",
    "tradeoff",
    "debate",
    "분석",
    "설계",
    "전략",
    "리뷰",
    "비교",
    "토론",
)

QUICK_HINTS = (
    "summary",
    "summarize",
    "translate",
    "translation",
    "quick",
    "short",
    "요약",
    "정리",
    "번역",
    "짧게",
)


@dataclass(slots=True)
class RoutingDecision:
    enabled: bool
    task_type: str
    provider: str
    model: str | None
    stripped_prompt: str
    reason: str


def infer_task_type(text: str) -> str:
    lowered = str(text or "").lower()
    if any(hint in lowered for hint in CODE_HINTS):
        return "code"
    if any(hint in lowered for hint in ANALYSIS_HINTS):
        return "analysis"
    if any(hint in lowered for hint in QUICK_HINTS):
        return "quick"
    return "general"


def _route_provider_for_task(task_type: str, session_provider: str) -> str:
    if task_type == "code":
        return "codex"
    if task_type == "analysis":
        return "claude"
    if task_type == "quick":
        return "gemini"
    return session_provider


def suggest_route(
    *,
    prompt: str,
    session_provider: str,
    session_model: str | None,
    default_models: Mapping[str, str | None],
) -> RoutingDecision:
    raw_prompt = str(prompt or "")
    match = AUTO_ROUTE_RE.match(raw_prompt)
    enabled = match is not None
    stripped_prompt = raw_prompt[match.end():].strip() if match else raw_prompt

    task_type = infer_task_type(stripped_prompt)
    provider = session_provider
    reason = "session"

    if enabled:
        forced_provider = (match.group("provider") or "").lower() if match else ""
        if forced_provider:
            provider = forced_provider
            reason = "forced_provider"
        else:
            provider = _route_provider_for_task(task_type, session_provider)
            reason = f"task_type:{task_type}"

    configured_default = default_models.get(provider)
    model = resolve_provider_default_model(provider, configured_default)
    if session_model and provider == session_provider:
        model = session_model

    return RoutingDecision(
        enabled=enabled,
        task_type=task_type,
        provider=provider,
        model=model,
        stripped_prompt=stripped_prompt,
        reason=reason,
    )
