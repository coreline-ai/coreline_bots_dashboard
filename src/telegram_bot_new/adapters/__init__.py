from .base import AdapterEvent, AdapterResumeRequest, AdapterRunRequest, CliAdapter
from .claude_adapter import ClaudeAdapter
from .codex_adapter import CodexAdapter
from .echo_adapter import EchoAdapter
from .gemini_adapter import GeminiAdapter


def get_adapter(name: str) -> CliAdapter:
    if name == "codex":
        return CodexAdapter()
    if name == "gemini":
        return GeminiAdapter()
    if name == "claude":
        return ClaudeAdapter()
    if name == "echo":
        return EchoAdapter()
    raise ValueError(f"unsupported adapter: {name}")
