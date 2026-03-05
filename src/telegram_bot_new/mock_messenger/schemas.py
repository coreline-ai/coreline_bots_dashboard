from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class MockSendRequest(BaseModel):
    token: str = Field(min_length=1)
    chat_id: int
    user_id: int = 10001
    text: str = Field(min_length=1)


class MockClearMessagesRequest(BaseModel):
    token: str = Field(min_length=1)
    chat_id: Optional[int] = None


class RateLimitRuleRequest(BaseModel):
    token: str = Field(min_length=1)
    method: str = Field(min_length=1)
    count: int = Field(ge=1, le=100)
    retry_after: int = Field(default=1, ge=1, le=120)


class BotCatalogAddRequest(BaseModel):
    bot_id: Optional[str] = None
    token: Optional[str] = None
    name: Optional[str] = None
    adapter: Literal["codex", "gemini", "claude", "echo"] = "codex"


class BotCatalogDeleteRequest(BaseModel):
    bot_id: str = Field(min_length=1)


CoworkRole = Literal["controller", "planner", "implementer", "qa", "executor", "integrator"]
SCENARIO_REQUIRED_KEYS = (
    "project_id",
    "objective",
    "brand_tone",
    "target_audience",
    "core_cta",
    "required_sections",
    "forbidden_elements",
    "constraints",
    "deadline",
    "priority",
)


class BotCatalogRoleUpdateRequest(BaseModel):
    bot_id: str = Field(min_length=1)
    role: CoworkRole


class BotCatalogNameUpdateRequest(BaseModel):
    bot_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ControlTowerRecoverRequest(BaseModel):
    bot_id: str = Field(min_length=1)
    token: Optional[str] = None
    chat_id: Optional[int] = None
    user_id: int = 9001
    strategy: Literal["stop_run", "restart_session"] = "stop_run"


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
    max_turn_sec: int = Field(default=60, ge=10, le=300)
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
    response_text: Optional[str] = None
    status: str
    error_text: Optional[str] = None
    started_at: int
    finished_at: Optional[int] = None
    duration_ms: Optional[int] = None


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
    adapter: Optional[str] = None


class DebateDecisionSummary(BaseModel):
    summary: Optional[str] = None
    conclusion: Optional[str] = None
    action: Optional[str] = None
    confidence_score: int = Field(ge=0, le=100, default=0)


class DebateStatusResponse(BaseModel):
    debate_id: str
    scope_key: Optional[str] = None
    topic: str
    status: Literal["queued", "running", "completed", "stopped", "failed"]
    rounds_total: int
    max_turn_sec: int
    fresh_session: bool
    stop_requested: bool
    created_at: int
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    error_summary: Optional[str] = None
    current_turn: Optional[DebateCurrentTurn] = None
    turns: list[DebateTurnView] = Field(default_factory=list)
    errors: list[DebateErrorView] = Field(default_factory=list)
    participants: list[DebateParticipantView] = Field(default_factory=list)
    decision_summary: Optional[DebateDecisionSummary] = None


class CoworkProfileRef(BaseModel):
    profile_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    bot_id: str = Field(min_length=1)
    token: str = Field(min_length=1)
    chat_id: int
    user_id: int
    role: CoworkRole = "implementer"


class CoworkStartRequest(BaseModel):
    task: str = Field(min_length=1)
    profiles: list[CoworkProfileRef] = Field(min_length=2)
    max_parallel: int = Field(default=3, ge=1, le=8)
    max_turn_sec: int = Field(default=60, ge=10, le=300)
    fresh_session: bool = True
    keep_partial_on_error: bool = True
    scenario: dict[str, Any]

    @field_validator("scenario")
    @classmethod
    def validate_scenario_contract(cls, value: dict[str, Any]) -> dict[str, Any]:
        missing: list[str] = []
        for key in SCENARIO_REQUIRED_KEYS:
            field_value = value.get(key)
            if isinstance(field_value, list):
                normalized = [str(item).strip() for item in field_value if str(item).strip()]
                if not normalized:
                    missing.append(key)
            elif not str(field_value or "").strip():
                missing.append(key)
        if missing:
            raise ValueError(f"scenario contract missing required fields: {', '.join(missing)}")
        return value


class CoworkCurrentActor(BaseModel):
    bot_id: str
    label: str
    role: CoworkRole


class CoworkStageView(BaseModel):
    id: int
    stage_no: int
    stage_type: str
    actor_bot_id: str
    actor_label: str
    actor_role: CoworkRole
    prompt_text: str
    response_text: Optional[str] = None
    status: str
    error_text: Optional[str] = None
    started_at: int
    finished_at: Optional[int] = None
    duration_ms: Optional[int] = None


class CoworkTaskView(BaseModel):
    id: int
    task_no: int
    title: str
    spec_json: dict[str, Any] = Field(default_factory=dict)
    assignee_bot_id: str
    assignee_label: str
    assignee_role: CoworkRole
    status: str
    response_text: Optional[str] = None
    error_text: Optional[str] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    duration_ms: Optional[int] = None


class CoworkErrorView(BaseModel):
    source: Literal["stage", "task"]
    source_id: int
    stage_type: Optional[str] = None
    task_no: Optional[int] = None
    bot_id: str
    label: str
    role: CoworkRole
    status: str
    error_text: str


class CoworkParticipantView(BaseModel):
    position: int
    profile_id: str
    label: str
    bot_id: str
    token: str
    chat_id: int | str
    user_id: int | str
    role: CoworkRole
    adapter: Optional[str] = None


class CoworkFinalReport(BaseModel):
    integrated_summary: Optional[str] = None
    conflicts: Optional[str] = None
    missing: Optional[str] = None
    recommended_fixes: Optional[str] = None
    final_conclusion: Optional[str] = None
    execution_checklist: Optional[str] = None
    execution_link: Optional[str] = None
    evidence_summary: Optional[str] = None
    qa_conclusion: Optional[str] = None
    qa_signoff: Optional[str] = None
    defect_summary: Optional[str] = None
    repro_steps: Optional[str] = None
    defects: list[dict[str, Any]] = Field(default_factory=list)
    completion_status: Optional[str] = None
    quality_gate_failures: list[str] = Field(default_factory=list)
    immediate_actions_top3: list[str] = Field(default_factory=list)


class CoworkArtifactFile(BaseModel):
    name: str
    path: str
    url: str
    size_bytes: int


class CoworkArtifacts(BaseModel):
    root_dir: str
    files: list[CoworkArtifactFile] = Field(default_factory=list)


class CoworkStatusResponse(BaseModel):
    cowork_id: str
    task: str
    status: Literal["queued", "running", "completed", "stopped", "failed"]
    max_parallel: int
    max_turn_sec: int
    fresh_session: bool
    keep_partial_on_error: bool
    stop_requested: bool
    created_at: int
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    error_summary: Optional[str] = None
    current_stage: Optional[
        Literal[
            "intake",
            "planning",
            "planning_review",
            "execution",
            "implementation",
            "integration",
            "qa",
            "rework",
            "controller_gate",
            "finalization",
        ]
    ] = None
    current_actor: Optional[CoworkCurrentActor] = None
    stages: list[CoworkStageView] = Field(default_factory=list)
    tasks: list[CoworkTaskView] = Field(default_factory=list)
    errors: list[CoworkErrorView] = Field(default_factory=list)
    participants: list[CoworkParticipantView] = Field(default_factory=list)
    final_report: Optional[CoworkFinalReport] = None
    artifacts: Optional[CoworkArtifacts] = None
