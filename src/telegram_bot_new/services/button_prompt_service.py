from __future__ import annotations

import re

from telegram_bot_new.db.repository import SessionView
from telegram_bot_new.db.models import Turn


class ButtonPromptService:
    def build_summary_prompt(self, *, session: SessionView, origin_turn: Turn, latest_turn: Turn | None) -> str:
        recent_user = (origin_turn.user_text or "").strip()
        recent_assistant = (origin_turn.assistant_text or "").strip()
        latest_assistant = (latest_turn.assistant_text or "").strip() if latest_turn else ""
        rolling = (session.rolling_summary_md or "").strip()

        return (
            "You are helping in Telegram. Create a concise Korean summary for the user.\n"
            "Output format:\n"
            "1) 핵심 요약 (5-8줄)\n"
            "2) 다음 액션 3개\n"
            "3) 주의할 점 1-2개\n\n"
            f"[Rolling Summary]\n{rolling or '(none)'}\n\n"
            f"[Origin User Request]\n{recent_user or '(none)'}\n\n"
            f"[Origin Assistant Response]\n{recent_assistant or '(none)'}\n\n"
            f"[Latest Assistant Response]\n{latest_assistant or '(none)'}\n"
        )

    def build_regen_prompt(self, *, session: SessionView, origin_turn: Turn) -> str:
        recent_user = (origin_turn.user_text or "").strip()
        recent_assistant = (origin_turn.assistant_text or "").strip()
        rolling = (session.rolling_summary_md or "").strip()
        return (
            "Regenerate an alternative answer for the same request.\n"
            "Constraints:\n"
            "- Use a different approach.\n"
            "- Be more concise and structured.\n"
            "- Keep practical and actionable style.\n\n"
            f"[Rolling Summary]\n{rolling or '(none)'}\n\n"
            f"[Original User Request]\n{recent_user or '(none)'}\n\n"
            f"[Previous Assistant Response]\n{recent_assistant or '(none)'}\n"
        )

    def build_next_prompt(self, *, session: SessionView, origin_turn: Turn, latest_assistant_text: str) -> str:
        recent_user = (origin_turn.user_text or "").strip()
        recent_assistant = (origin_turn.assistant_text or "").strip()
        rolling = (session.rolling_summary_md or "").strip()
        urls = self._extract_urls(latest_assistant_text or recent_assistant)
        url_block = "\n".join(f"- {url}" for url in urls[:6]) if urls else "(none)"
        return (
            "Suggest 3 next recommendations for Telegram user.\n"
            "Output format for each item:\n"
            "- title\n"
            "- why (one line)\n"
            "- optional link\n\n"
            f"[Rolling Summary]\n{rolling or '(none)'}\n\n"
            f"[User Request]\n{recent_user or '(none)'}\n\n"
            f"[Assistant Context]\n{recent_assistant or '(none)'}\n\n"
            f"[Detected Links]\n{url_block}\n"
        )

    def _extract_urls(self, text: str) -> list[str]:
        if not text:
            return []
        matches = re.findall(r"https?://[^\s)>\"]+", text)
        seen: set[str] = set()
        urls: list[str] = []
        for url in matches:
            normalized = url.rstrip(".,;!?)")
            if normalized in seen:
                continue
            seen.add(normalized)
            urls.append(normalized)
        return urls
