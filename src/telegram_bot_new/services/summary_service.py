from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SummaryInput:
    previous_summary: str
    user_text: str
    assistant_text: str
    command_notes: list[str]
    error_text: str | None


class SummaryService:
    MAX_LENGTH = 4000

    def build_summary(self, data: SummaryInput) -> str:
        goals = self._pick_line(data.user_text, fallback="- Process the current user request")
        decisions = self._pick_line(data.assistant_text, fallback="- Assistant response generated")
        constraints = "- Keep Telegram to CLI bridge context stable"
        open_issues = f"- {data.error_text}" if data.error_text else "- none"
        artifacts = (
            "\n".join(f"- {line}" for line in data.command_notes[:10])
            if data.command_notes
            else "- no command execution notes"
        )

        previous_block = data.previous_summary.strip()
        if previous_block:
            previous_block = f"## Previous Summary\n{previous_block}\n\n"

        summary = (
            f"{previous_block}"
            f"## Goal\n{goals}\n\n"
            f"## Decisions\n{decisions}\n\n"
            f"## Constraints\n{constraints}\n\n"
            f"## Open Issues\n{open_issues}\n\n"
            f"## Key Artifacts\n{artifacts}\n"
        )
        return self._trim(summary)

    def build_recovery_preamble(self, summary_md: str) -> str:
        if not summary_md.strip():
            return ""
        return (
            "[Session Memory Summary]\n"
            "Continue work while preserving prior context using this summary.\n\n"
            f"{self._trim(summary_md)}"
        )

    def _pick_line(self, text: str, fallback: str) -> str:
        text = (text or "").strip()
        if not text:
            return fallback
        single = text.replace("\n", " ").strip()
        if len(single) <= 300:
            return f"- {single}"
        return f"- {single[:297]}..."

    def _trim(self, text: str) -> str:
        if len(text) <= self.MAX_LENGTH:
            return text
        return text[: self.MAX_LENGTH - 16] + "\n\n[truncated]"
