from hashlib import sha256
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.domain.models import DecisionFingerprintMaterial


class ProofIntegrityError(ValueError):
    """A persisted v2 proof's complete artifact hash does not match its contents."""


TIMESTAMP_FIELD_NAMES = frozenset({"evaluated_at", "created_at", "settled_at", "value_date", "now"})


def _canonical_utc_timestamp(value: datetime | str) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("canonical proof timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_utc_timestamps(value: Any, field_name: str | None = None) -> Any:
    """Normalize only named proof timestamp fields; all other strings remain exact evidence."""
    if isinstance(value, BaseModel):
        return normalize_utc_timestamps(value.model_dump(mode="python"), field_name)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): normalize_utc_timestamps(item, str(key)) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [normalize_utc_timestamps(item, field_name) for item in value]
    if field_name in TIMESTAMP_FIELD_NAMES and isinstance(value, datetime | str):
        return _canonical_utc_timestamp(value)
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        normalize_utc_timestamps(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return value
    raise TypeError("proof fingerprint material must be a Pydantic model or mapping")


def _sorted_source_rows(rows: Any) -> list[dict[str, Any]]:
    normalized_rows = [normalize_utc_timestamps(row) for row in rows]
    return sorted(normalized_rows, key=lambda row: (row["table"], row["id"], row["raw_hash"]))


def _decision_canonical_dict(material: DecisionFingerprintMaterial | Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(material)
    subject = _mapping(payload["subject"])
    configuration = _mapping(payload["configuration"])
    return {
        "schema_version": "proof-decision-fingerprint/v2",
        "subject": {"type": subject["subject_type"], "id": subject["subject_id"]},
        "rule": {"name": payload["rule_name"], "version": payload["rule_version"]},
        "configuration": {"version": configuration["version"], "values": configuration["values"]},
        "source_rows": _sorted_source_rows(payload["source_rows"]),
        "evidence_inputs": payload["evidence_inputs"],
        "evaluated_at": payload["evaluated_at"],
        "status": payload["status"],
        "formula": payload["formula"],
        "result": payload["result"],
        "evidence": payload["evidence"],
        "decision_score": payload["decision_score"],
        "decision_reasons": payload["decision_reasons"],
        "classification": payload["classification"],
        "exception_type": payload["exception_type"],
        "unresolved_reason": payload["unresolved_reason"],
    }


def decision_fingerprint(material: DecisionFingerprintMaterial | Mapping[str, Any]) -> str:
    return f"sha256:{sha256(canonical_json(_decision_canonical_dict(material))).hexdigest()}"


def _artifact_canonical_payload(proof_payload: Mapping[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in proof_payload.items() if key != "artifact_fingerprint"}
    if "source_rows" in payload:
        payload["source_rows"] = _sorted_source_rows(payload["source_rows"])
    return payload


def artifact_fingerprint(proof_payload: Mapping[str, Any]) -> str:
    return f"sha256:{sha256(canonical_json(_artifact_canonical_payload(proof_payload))).hexdigest()}"


def verify_artifact_fingerprint(proof_payload: Mapping[str, Any]) -> None:
    stored = proof_payload.get("artifact_fingerprint")
    expected = artifact_fingerprint(proof_payload)
    if not isinstance(stored, str) or stored != expected:
        raise ProofIntegrityError("proof artifact fingerprint mismatch")


def fingerprint_material(material: Any) -> str:
    """Legacy v1 decision fingerprint serialization retained for historical proof verification."""
    payload = material.model_dump(mode="json") if hasattr(material, "model_dump") else material
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"
