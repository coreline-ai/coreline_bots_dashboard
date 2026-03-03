from __future__ import annotations

import os
import platform
import re
import shutil
from pathlib import Path


_PROVIDER_ENV_BIN_KEY: dict[str, str] = {
    "codex": "CODEX_BIN",
    "gemini": "GEMINI_BIN",
    "claude": "CLAUDE_BIN",
}

_PROVIDER_DEFAULT_COMMAND: dict[str, str] = {
    "codex": "codex",
    "gemini": "gemini",
    "claude": "claude",
}


def _resolve_from_env(env_key: str) -> str | None:
    raw = (os.getenv(env_key) or "").strip()
    if not raw:
        return None

    expanded = str(Path(raw).expanduser())
    looks_like_path = any(sep in expanded for sep in ("/", "\\")) or expanded.startswith(".")
    if looks_like_path:
        candidate = Path(expanded)
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return None

    return shutil.which(expanded)


def _parse_chatgpt_extension_version(dirname: str) -> tuple[int, ...]:
    matched = re.search(r"openai\.chatgpt-([0-9][0-9A-Za-z._-]*)$", dirname)
    if matched is None:
        return tuple()

    tokens = re.split(r"[._-]", matched.group(1))
    numbers: list[int] = []
    for token in tokens:
        if token.isdigit():
            numbers.append(int(token))
        else:
            break
    return tuple(numbers)


def _extension_codex_relative_paths() -> tuple[str, ...]:
    system = platform.system().lower()
    if system == "darwin":
        return (
            "bin/macos-aarch64/codex",
            "bin/macos-x64/codex",
            "bin/darwin-arm64/codex",
            "bin/darwin-x64/codex",
        )
    if system == "windows":
        return (
            "bin/win32-x64/codex.exe",
            "bin/win32-arm64/codex.exe",
            "bin/windows-x64/codex.exe",
        )
    return (
        "bin/linux-x64/codex",
        "bin/linux-arm64/codex",
    )


def _resolve_codex_from_chatgpt_extensions() -> str | None:
    roots = (
        Path.home() / ".antigravity" / "extensions",
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".vscode-insiders" / "extensions",
    )
    rel_paths = _extension_codex_relative_paths()
    candidates: list[tuple[tuple[int, ...], float, Path]] = []

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for extension_dir in root.glob("openai.chatgpt-*"):
            if not extension_dir.is_dir():
                continue
            version = _parse_chatgpt_extension_version(extension_dir.name)
            for rel in rel_paths:
                candidate = extension_dir / rel
                if not candidate.exists() or not os.access(candidate, os.X_OK):
                    continue
                stat = candidate.stat()
                candidates.append((version, stat.st_mtime, candidate))
                break

    if not candidates:
        return None

    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return str(candidates[0][2].resolve())


def resolve_provider_binary(provider: str) -> str | None:
    normalized = (provider or "").strip().lower()
    if not normalized:
        return None

    env_key = _PROVIDER_ENV_BIN_KEY.get(normalized)
    if env_key:
        env_candidate = _resolve_from_env(env_key)
        if env_candidate:
            return env_candidate

    default_command = _PROVIDER_DEFAULT_COMMAND.get(normalized, normalized)
    path_candidate = shutil.which(default_command)
    if path_candidate:
        return path_candidate

    if normalized == "codex":
        return _resolve_codex_from_chatgpt_extensions()
    return None


def command_for_provider(provider: str) -> str:
    return resolve_provider_binary(provider) or provider


def is_provider_installed(provider: str) -> bool:
    return resolve_provider_binary(provider) is not None

