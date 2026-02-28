from __future__ import annotations

from pydantic import BaseModel, Field


class MockSendRequest(BaseModel):
    token: str = Field(min_length=1)
    chat_id: int
    user_id: int = 10001
    text: str = Field(min_length=1)


class RateLimitRuleRequest(BaseModel):
    token: str = Field(min_length=1)
    method: str = Field(min_length=1)
    count: int = Field(ge=1, le=100)
    retry_after: int = Field(default=1, ge=1, le=120)
