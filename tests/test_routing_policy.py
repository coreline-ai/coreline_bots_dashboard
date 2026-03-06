from __future__ import annotations

from telegram_bot_new.routing_policy import infer_task_type, suggest_route


def test_infer_task_type_code_and_analysis_and_quick() -> None:
    assert infer_task_type("Please fix this bug in python code") == "code"
    assert infer_task_type("아키텍처 분석과 트레이드오프 정리") == "analysis"
    assert infer_task_type("짧게 요약해줘") == "quick"


def test_suggest_route_keeps_session_when_auto_prefix_absent() -> None:
    decision = suggest_route(
        prompt="일반 질문",
        session_provider="gemini",
        session_model="gemini-2.5-pro",
        default_models={"gemini": "gemini-2.5-flash"},
    )
    assert decision.enabled is False
    assert decision.provider == "gemini"
    assert decision.model == "gemini-2.5-pro"
    assert decision.stripped_prompt == "일반 질문"


def test_suggest_route_with_auto_prefix_routes_by_task_type() -> None:
    decision = suggest_route(
        prompt="@auto 코드 리팩토링 해줘",
        session_provider="gemini",
        session_model=None,
        default_models={"codex": "gpt-5.4", "gemini": "gemini-2.5-flash", "claude": "claude-sonnet-4-5"},
    )
    assert decision.enabled is True
    assert decision.task_type == "code"
    assert decision.provider == "codex"
    assert decision.model == "gpt-5.4"
    assert decision.stripped_prompt == "코드 리팩토링 해줘"


def test_suggest_route_with_forced_provider() -> None:
    decision = suggest_route(
        prompt="@auto:claude 성능 전략 비교",
        session_provider="gemini",
        session_model=None,
        default_models={"codex": "gpt-5.4", "gemini": "gemini-2.5-flash", "claude": "claude-sonnet-4-5"},
    )
    assert decision.enabled is True
    assert decision.provider == "claude"
    assert decision.reason == "forced_provider"
    assert decision.model == "claude-sonnet-4-5"
    assert decision.stripped_prompt == "성능 전략 비교"
