"""Explicit, lossless reader for pre-v2 Proof Objects."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.domain.enums import Classification, Decision, ExceptionType
from app.domain.models import FrozenModel, MatchEvidence, ProofResult, SourceReference
from app.proofs.fingerprint import ProofIntegrityError, fingerprint_material, verify_artifact_fingerprint


class LegacyProofSchemaUnavailable(ValueError):
    """The stored payload cannot be read as the exact v1 schema it originally used."""


class LegacyProofObject(FrozenModel):
    """The v1 shape, preserved without adding any v2 identity or policy fields."""

    proof_id: str
    tenant_id: str
    run_id: str
    source_snapshot_id: str
    status: Decision
    source_rows: tuple[SourceReference, ...]
    rule_name: str
    rule_version: str
    configuration_version: str
    inputs: dict[str, Any]
    formula: str
    result: ProofResult
    evidence: MatchEvidence
    decision_score: int
    decision_reasons: tuple[str, ...]
    classification: Classification = Classification.CALCULATED
    exception_type: ExceptionType | None = None
    unresolved_reason: str | None = None
    proof_fingerprint: str
    supersedes_proof_id: str | None = None
    created_at: Any

    def verify_original_decision_fingerprint(self) -> None:
        material = self.model_dump(
            mode="json",
            include={
                "status",
                "source_rows",
                "inputs",
                "formula",
                "result",
                "evidence",
                "decision_score",
                "decision_reasons",
                "classification",
                "exception_type",
                "unresolved_reason",
            },
        )
        if fingerprint_material(material) != self.proof_fingerprint:
            raise ProofIntegrityError("legacy proof decision fingerprint mismatch")


def parse_stored_proof(payload_json: str):
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise LegacyProofSchemaUnavailable("LEGACY_PROOF_SCHEMA_UNAVAILABLE") from exc
    if not isinstance(payload, dict):
        raise LegacyProofSchemaUnavailable("LEGACY_PROOF_SCHEMA_UNAVAILABLE")
    if payload.get("schema_version") == "proof-object/v2":
        verify_artifact_fingerprint(payload)
        from app.domain.models import ProofObject

        return ProofObject.model_validate(payload)
    try:
        proof = LegacyProofObject.model_validate(payload)
    except ValidationError as exc:
        raise LegacyProofSchemaUnavailable("LEGACY_PROOF_SCHEMA_UNAVAILABLE") from exc
    proof.verify_original_decision_fingerprint()
    return proof
