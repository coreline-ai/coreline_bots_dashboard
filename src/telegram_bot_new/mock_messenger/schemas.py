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


class DebateProfileRef(BaseModel):
    profile_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    bot_id: str = Field(min_length=1)
    token: str = Field(min_length=1)
    chat_id: int
    user_id: int


class DebateStartRequest(BaseModel):
    topic: str = Field(min_length=1)
    profiles: list[DebateProfileRef] = Field(min_length=2)
    rounds: int = Field(default=3, ge=1, le=10)
    max_turn_sec: int = Field(default=90, ge=10, le=300)
    fresh_session: bool = True


class DebateCurrentTurn(BaseModel):
    round: int
    position: int
    speaker_bot_id: str
    speaker_label: str
    started_at: int


class DebateTurnView(BaseModel):
    id: int
    round_no: int
    speaker_position: int
    speaker_bot_id: str
    speaker_label: str
    prompt_text: str
    response_text: str | None = None
    status: str
    error_text: str | None = None
    started_at: int
    finished_at: int | None = None
    duration_ms: int | None = None


class DebateErrorView(BaseModel):
    turn_id: int
    round_no: int
    speaker_bot_id: str
    speaker_label: str
    status: str
    error_text: str


class DebateParticipantView(BaseModel):
    position: int
    profile_id: str
    label: str
    bot_id: str
    token: str
    chat_id: int | str
    user_id: int | str
    adapter: str | None = None


class DebateStatusResponse(BaseModel):
    debate_id: str
    topic: str
    status: Literal["queued", "running", "completed", "stopped", "failed"]
    rounds_total: int
    max_turn_sec: int
    fresh_session: bool
    stop_requested: bool
    created_at: int
    started_at: int | None = None
    finished_at: int | None = None
    error_summary: str | None = None
    current_turn: DebateCurrentTurn | None = None
    turns: list[DebateTurnView] = Field(default_factory=list)
    errors: list[DebateErrorView] = Field(default_factory=list)
    participants: list[DebateParticipantView] = Field(default_factory=list)
