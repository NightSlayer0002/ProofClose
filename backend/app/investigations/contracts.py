from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field, StrictStr


ToolName = Literal[
    "close_summary",
    "close_blockers",
    "settlement_lookup",
    "exception_breakdown",
    "pending_settlements",
    "proof_explanation",
    "source_lineage",
    "product_help",
    "REFUSE",
]

AnswerMode = Literal["CURRENT_FACT", "EVIDENCE_GUIDANCE", "GENERAL_HELP", "UNABLE_TO_VERIFY"]
ANSWER_LABELS: dict[str, str] = {
    "CURRENT_FACT": "Verified from evidence",
    "EVIDENCE_GUIDANCE": "Verified + guidance",
    "GENERAL_HELP": "General guidance",
    "UNABLE_TO_VERIFY": "Unable to verify",
}


class AssistantContext(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    run_id: str = Field(min_length=1, max_length=64)
    settlement_id: str | None = Field(default=None, max_length=64)
    proof_id: str | None = Field(default=None, max_length=64)
    page: str | None = Field(default=None, max_length=32)


class CopilotIntent(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    mode: AnswerMode
    reason: str = Field(min_length=1, max_length=240)


class RecommendedAction(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    code: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=160)
    detail: str = Field(min_length=1, max_length=500)


class ConversationTurn(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=500)


class ToolSelection(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    name: ToolName
    # Planner values must be strings before validation; never let Pydantic
    # coerce attacker-controlled numbers/bools into trusted identifiers.
    arguments: dict[str, StrictStr] = Field(default_factory=dict)
    route: Literal["DIRECT_TOOL", "PLANNER_TOOL", "REFUSE"] = "DIRECT_TOOL"
    reason: str = "Approved deterministic evidence tool"


class ClaimValidation(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    accepted: bool
    unsupported_claim_count: int = Field(ge=0)
    unsupported_tokens: tuple[str, ...] = ()


class AssistantCitations(BaseModel):
    """The minimal evidence references used to answer one assistant question."""

    model_config = {"frozen": True, "extra": "forbid"}

    proof_ids: tuple[str, ...] = ()
    source_rows: tuple[str, ...] = ()
    support_scope: Literal["DIRECT", "AGGREGATE"]


class ProviderStatus(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    configuration_status: Literal["not_configured", "configured"]
    reachability_status: Literal["not_probed", "reachable", "unreachable"]
    model: str | None = None
    failure_category: str | None = None
    last_probe_at: str | None = None
    prompt_version: str = "proofclose-assistant/v1"


class ProviderResult(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    content: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model: str
    latency_ms: int = Field(default=0, ge=0)


class GeneralHelpProvider(Protocol):
    def general_help(
        self,
        question: str,
        history: tuple[ConversationTurn, ...],
        *,
        before_attempt: Callable[[], bool],
    ) -> ProviderResult: ...


class AssistantAnswer(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    status: str
    route: str
    tool_name: str | None = None
    question: str = Field(min_length=1, max_length=1000)
    explained_paise: int | None = None
    unresolved_paise: int | None = None
    canonical: dict[str, Any] = Field(default_factory=dict)
    narration: str | None = None
    narration_status: str
    lines: list[dict[str, Any]] = Field(default_factory=list)
    proof_ids: list[str] = Field(default_factory=list)
    citations: AssistantCitations = Field(
        default_factory=lambda: AssistantCitations(support_scope="DIRECT")
    )
    supporting_record_count: int = Field(default=0, ge=0)
    run_record_count: int = Field(default=0, ge=0)
    calculation_count: int = Field(default=0, ge=0)
    unsupported_factual_claims: int = Field(default=0, ge=0)
    provider: ProviderStatus
    estimated_cost: str | int | float = "unavailable"
    message: str
    answer_mode: AnswerMode = "CURRENT_FACT"
    answer_label: str = "Verified from evidence"
    detail: str | None = None
    recommended_actions: tuple[RecommendedAction, ...] = ()
    resolution_brief: dict[str, Any] | None = None
    technical_details: dict[str, Any] = Field(default_factory=dict)
