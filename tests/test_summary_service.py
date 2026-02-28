from telegram_bot_new.services.summary_service import SummaryInput, SummaryService


def test_summary_contains_required_sections() -> None:
    service = SummaryService()

    summary = service.build_summary(
        SummaryInput(
            previous_summary="old",
            user_text="Build Telegram bridge",
            assistant_text="Implemented worker and streaming",
            command_notes=["pytest", "codex exec --json"],
            error_text=None,
        )
    )

    assert "## Goal" in summary
    assert "## Decisions" in summary
    assert "## Constraints" in summary
    assert "## Open Issues" in summary
    assert "## Key Artifacts" in summary


def test_summary_trim_applies_max_length() -> None:
    service = SummaryService()
    huge = "x" * 10000

    summary = service.build_summary(
        SummaryInput(
            previous_summary=huge,
            user_text="u",
            assistant_text="a",
            command_notes=[],
            error_text=None,
        )
    )

    assert len(summary) <= service.MAX_LENGTH


def test_recovery_preamble_empty_when_no_summary() -> None:
    service = SummaryService()

    assert service.build_recovery_preamble("") == ""
    assert "Session Memory Summary" in service.build_recovery_preamble("abc")
