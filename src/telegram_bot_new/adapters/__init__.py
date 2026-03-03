from .base import AdapterEvent, AdapterResumeRequest, AdapterRunRequest, CliAdapter
from .claude_adapter import ClaudeAdapter
from .codex_adapter import CodexAdapter
from .echo_adapter import EchoAdapter
from .gemini_adapter import GeminiAdapter
from telegram_bot_new.provider_binaries import command_for_provider


def get_adapter(name: str) -> CliAdapter:
    if name == "codex":
        return CodexAdapter(codex_bin=command_for_provider("codex"))
    if name == "gemini":
        return GeminiAdapter(gemini_bin=command_for_provider("gemini"))
    if name == "claude":
        return ClaudeAdapter(claude_bin=command_for_provider("claude"))
    if name == "echo":
        return EchoAdapter()
    raise ValueError(f"unsupported adapter: {name}")
