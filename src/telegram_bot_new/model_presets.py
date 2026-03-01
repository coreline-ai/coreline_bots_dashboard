from __future__ import annotations

from typing import Mapping, Optional

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

PREFERRED_DEFAULT_MODEL_BY_PROVIDER: dict[str, str] = {
    "codex": "gpt-5.3-codex",
    # Keep Gemini usable by default even when Pro terminal capacity is exhausted.
    "gemini": "gemini-2.5-flash",
    "claude": "claude-sonnet-4-5",
}


def get_available_models(provider: str) -> tuple[str, ...]:
    return AVAILABLE_MODELS_BY_PROVIDER.get(provider, tuple())


def is_allowed_model(provider: str, model: str) -> bool:
    return model in get_available_models(provider)


def resolve_provider_default_model(provider: str, configured_default: Optional[str]) -> Optional[str]:
    models = get_available_models(provider)
    if not models:
        return None
    if configured_default and configured_default in models:
        return configured_default
    preferred = PREFERRED_DEFAULT_MODEL_BY_PROVIDER.get(provider)
    if preferred and preferred in models:
        return preferred
    return models[0]


def resolve_selected_model(
    *,
    provider: str,
    session_model: Optional[str],
    default_models: Optional[Mapping[str, Optional[str]]],
) -> Optional[str]:
    if session_model and is_allowed_model(provider, session_model):
        return session_model
    configured_default = (default_models or {}).get(provider) if default_models else None
    return resolve_provider_default_model(provider, configured_default)
