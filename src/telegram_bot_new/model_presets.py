from __future__ import annotations

from typing import Mapping

SUPPORTED_CLI_PROVIDERS: tuple[str, ...] = ("codex", "gemini", "claude")

AVAILABLE_MODELS_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    "codex": (
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2-codex",
        "gpt-5.1-codex-max",
        "gpt-5.2",
        "gpt-5.1-codex-mini",
        "gpt-5",
    ),
    "gemini": ("gemini-2.5-pro", "gemini-2.5-flash"),
    "claude": ("claude-sonnet-4-5",),
}


def get_available_models(provider: str) -> tuple[str, ...]:
    return AVAILABLE_MODELS_BY_PROVIDER.get(provider, tuple())


def is_allowed_model(provider: str, model: str) -> bool:
    return model in get_available_models(provider)


def resolve_provider_default_model(provider: str, configured_default: str | None) -> str | None:
    models = get_available_models(provider)
    if not models:
        return None
    if configured_default and configured_default in models:
        return configured_default
    return models[0]


def resolve_selected_model(
    *,
    provider: str,
    session_model: str | None,
    default_models: Mapping[str, str | None] | None,
) -> str | None:
    if session_model and is_allowed_model(provider, session_model):
        return session_model
    configured_default = (default_models or {}).get(provider) if default_models else None
    return resolve_provider_default_model(provider, configured_default)
