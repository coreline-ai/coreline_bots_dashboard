from __future__ import annotations

from pathlib import Path

from telegram_bot_new.provider_binaries import command_for_provider, is_provider_installed, resolve_provider_binary


def _make_exec(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def test_resolve_provider_binary_prefers_env_path(tmp_path: Path, monkeypatch) -> None:
    codex_path = tmp_path / "bin" / "codex"
    _make_exec(codex_path)

    monkeypatch.setenv("CODEX_BIN", str(codex_path))
    monkeypatch.setattr("telegram_bot_new.provider_binaries.shutil.which", lambda _name: None)

    assert resolve_provider_binary("codex") == str(codex_path.resolve())
    assert is_provider_installed("codex") is True


def test_resolve_provider_binary_falls_back_to_chatgpt_extension(tmp_path: Path, monkeypatch) -> None:
    old_codex = tmp_path / ".antigravity" / "extensions" / "openai.chatgpt-0.4.78-universal" / "bin" / "macos-aarch64" / "codex"
    new_codex = tmp_path / ".antigravity" / "extensions" / "openai.chatgpt-0.4.79-darwin-arm64" / "bin" / "macos-aarch64" / "codex"
    _make_exec(old_codex)
    _make_exec(new_codex)

    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("telegram_bot_new.provider_binaries.shutil.which", lambda _name: None)
    monkeypatch.setattr("telegram_bot_new.provider_binaries.platform.system", lambda: "Darwin")

    assert resolve_provider_binary("codex") == str(new_codex.resolve())


def test_command_for_provider_returns_name_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_BIN", raising=False)
    monkeypatch.setattr("telegram_bot_new.provider_binaries.shutil.which", lambda _name: None)

    assert is_provider_installed("gemini") is False
    assert command_for_provider("gemini") == "gemini"
