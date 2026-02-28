from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MockSendRequest(BaseModel):
    token: str = Field(min_length=1)
    chat_id: int
    user_id: int = 10001
    text: str = Field(min_length=1)


class MockClearMessagesRequest(BaseModel):
    token: str = Field(min_length=1)
    chat_id: int | None = None


class RateLimitRuleRequest(BaseModel):
    token: str = Field(min_length=1)
    method: str = Field(min_length=1)
    count: int = Field(ge=1, le=100)
    retry_after: int = Field(default=1, ge=1, le=120)


class BotCatalogAddRequest(BaseModel):
    bot_id: str | None = None
    token: str | None = None
    name: str | None = None
    adapter: Literal["codex", "gemini", "claude", "echo"] = "gemini"


class BotCatalogDeleteRequest(BaseModel):
    bot_id: str = Field(min_length=1)
