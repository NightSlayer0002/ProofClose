from typing import Literal
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.investigations.contracts import ConversationTurn


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def visible_text(value: str, field_name: str, minimum: int = 1) -> str:
    cleaned = value.strip()
    if len(cleaned) < minimum or not any(char.isprintable() and not char.isspace() for char in cleaned):
        raise ValueError(f"{field_name} must contain visible text")
    return cleaned


class RunRequest(StrictRequest):
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=64)
    evaluated_at: datetime | None = None

    @field_validator("evaluated_at")
    @classmethod
    def aware_evaluation_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("evaluated_at requires a timezone offset")
        return value.astimezone(timezone.utc) if value is not None else None


class SnapshotRequest(StrictRequest):
    source_ids: list[str] = Field(min_length=1, max_length=16)

    @field_validator("source_ids")
    @classmethod
    def bounded_source_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 64 for value in values):
            raise ValueError("source_ids must contain bounded non-empty identifiers")
        return values


class InvestigationRequest(StrictRequest):
    run_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=1000)
    settlement_id: str | None = Field(default=None, min_length=1, max_length=64)
    proof_id: str | None = Field(default=None, min_length=1, max_length=64)
    page: str | None = Field(default=None, min_length=1, max_length=64)
    history: list[ConversationTurn] = Field(default_factory=list, max_length=6)

    @field_validator("question")
    @classmethod
    def visible_question(cls, value: str) -> str:
        return visible_text(value, "question")


class ReviewRequest(StrictRequest):
    action: Literal["APPROVE", "REJECT", "LEAVE_UNRESOLVED"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def visible_reason(cls, value: str) -> str:
        return visible_text(value, "reason", minimum=5)


class ChallengeRequest(StrictRequest):
    feedback_type: Literal["INCORRECT_MATCH", "INCORRECT_EXCEPTION", "PROOF_UNCLEAR", "OTHER"]
    comment: str = Field(min_length=1, max_length=2000)

    @field_validator("comment")
    @classmethod
    def visible_comment(cls, value: str) -> str:
        return visible_text(value, "comment", minimum=5)


class CloseApprovalRequest(StrictRequest):
    run_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def visible_reason(cls, value: str) -> str:
        return visible_text(value, "reason", minimum=5)
