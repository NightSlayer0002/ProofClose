from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any
from typing import Mapping
from collections.abc import Iterator

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.domain.enums import Classification, Decision, ExceptionType, SubjectType


class FrozenModel(BaseModel):
    model_config = {"frozen": True, "extra": "forbid", "arbitrary_types_allowed": True}


class FrozenIntMapping(Mapping[str, int]):
    def __init__(self, value: Mapping[str, int] | dict[str, int]) -> None:
        self._values = MappingProxyType(dict(value))

    def __getitem__(self, key: str) -> int:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self._values) == dict(other)
        return NotImplemented

    def as_dict(self) -> dict[str, int]:
        return dict(self._values)

    def __copy__(self) -> "FrozenIntMapping":
        return FrozenIntMapping(self._values)

    def __deepcopy__(self, memo: dict[int, object]) -> "FrozenIntMapping":
        copied = FrozenIntMapping(self._values)
        memo[id(self)] = copied
        return copied


class CanonicalTimestampModel(FrozenModel):
    """Normalizes source timestamps once they cross into typed domain records."""

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def timestamps_are_utc(cls, value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must be timezone-aware")
            return value.astimezone(timezone.utc)
        return value


class ReconRow(CanonicalTimestampModel):
    tenant_id: str
    source_id: str
    raw_record_id: str
    entity_id: str
    type: str
    debit_paise: int = 0
    credit_paise: int = 0
    amount_paise: int = 0
    fee_paise: int = 0
    tax_paise: int = 0
    settlement_id: str | None = None
    settlement_utr: str | None = None
    order_id: str | None = None
    created_at: datetime | None = None
    settled_at: datetime | None = None


class MatchEvidence(FrozenModel):
    utr_exact: bool
    amount_exact: bool
    settlement_ledger_consistent: bool
    temporal_consistency: bool
    candidate_count: int = Field(ge=0)
    amount_delta_paise: int

    @property
    def supports_auto_verification(self) -> bool:
        return (
            self.utr_exact
            and self.amount_exact
            and self.settlement_ledger_consistent
            and self.temporal_consistency
            and self.candidate_count == 1
            and self.amount_delta_paise == 0
        )


class OrderEvidence(FrozenModel):
    payment_row_count: int = Field(ge=0)
    settled_payment_paise: int
    expected_order_payment_paise: int
    excess_payment_paise: int


class MerchantOrder(CanonicalTimestampModel):
    tenant_id: str
    source_id: str
    raw_record_id: str
    order_id: str
    amount_paise: int
    amount_paid_paise: int
    amount_due_paise: int = 0
    currency: str = "INR"
    status: str = "paid"
    partial_payment: bool = False
    attempts: int = Field(default=1, ge=0)
    created_at: datetime | None = None


class Settlement(CanonicalTimestampModel):
    tenant_id: str
    source_id: str
    raw_record_id: str
    settlement_id: str
    amount_paise: int
    status: str
    utr: str | None = None
    fees_paise: int = 0
    tax_paise: int = 0
    created_at: datetime | None = None


class BankLine(CanonicalTimestampModel):
    tenant_id: str
    source_id: str
    raw_record_id: str
    bank_ref: str
    utr: str | None = None
    credit_amount_paise: int
    value_date: datetime | None = None
    narration: str = ""


class SourceReference(FrozenModel):
    table: str
    id: str
    raw_hash: str


class ProofResult(FrozenModel):
    expected_paise: int
    observed_paise: int | None
    delta_paise: int | None


class ProofSubject(FrozenModel):
    subject_type: SubjectType
    subject_id: str = Field(min_length=1)


class ConfigurationBundle(FrozenModel):
    version: str = Field(min_length=1)
    values: FrozenIntMapping

    @field_validator("values", mode="before")
    @classmethod
    def values_must_be_immutable(cls, value: object) -> FrozenIntMapping:
        if isinstance(value, FrozenIntMapping):
            return value
        return FrozenIntMapping(dict(value))

    @field_serializer("values")
    def serialize_values(self, value: FrozenIntMapping) -> dict[str, int]:
        return value.as_dict()


class DecisionFingerprintMaterial(FrozenModel):
    """The decision-bearing fields that are bound independently of artifact identity."""

    subject: ProofSubject
    rule_name: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    configuration: ConfigurationBundle
    source_rows: tuple[SourceReference, ...]
    evidence_inputs: dict[str, Any]
    evaluated_at: datetime
    status: Decision
    formula: str
    result: ProofResult
    evidence: MatchEvidence | OrderEvidence
    decision_score: int
    decision_reasons: tuple[str, ...]
    classification: Classification = Classification.CALCULATED
    exception_type: ExceptionType | None = None
    unresolved_reason: str | None = None

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value


class DecisionMaterial(DecisionFingerprintMaterial):
    """Typed output of a deterministic reconciliation rule."""


class ProofObject(DecisionFingerprintMaterial):
    schema_version: str = "proof-object/v2"
    proof_id: str
    tenant_id: str
    run_id: str
    source_snapshot_id: str
    decision_fingerprint: str
    supersedes_proof_id: str | None = None
    created_at: datetime
    artifact_fingerprint: str

    @field_validator("schema_version")
    @classmethod
    def schema_must_be_v2(cls, value: str) -> str:
        if value != "proof-object/v2":
            raise ValueError("schema_version must be proof-object/v2")
        return value

    @field_validator("evaluated_at", "created_at", mode="before")
    @classmethod
    def stored_timestamp_strings_must_be_canonical_utc_z(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("stored timestamps must use canonical UTC-Z") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("stored timestamps must use canonical UTC-Z")
            canonical = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if value != canonical:
                raise ValueError("stored timestamps must use canonical UTC-Z")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @property
    def proof_fingerprint(self) -> str:
        """Compatibility accessor for consumers that display the decision fingerprint."""
        return self.decision_fingerprint

    @property
    def configuration_version(self) -> str:
        """Compatibility accessor for consumers that display the configuration version."""
        return self.configuration.version

    @property
    def inputs(self) -> dict[str, Any]:
        """Compatibility accessor for consumers that display the persisted evidence inputs."""
        return self.evidence_inputs
