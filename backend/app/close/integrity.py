"""Canonical hashing and verification for immutable close packs."""

from hashlib import sha256
import json
from typing import Any


class ClosePackIntegrityError(ValueError):
    """A persisted close pack no longer matches its authenticated bytes."""


def canonical_pack_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pack_fingerprint(payload: dict[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "pack_fingerprint"}
    return f"sha256:{sha256(canonical_pack_json(material)).hexdigest()}"


def storage_hash(payload_json: str | bytes) -> str:
    raw = payload_json if isinstance(payload_json, bytes) else payload_json.encode("utf-8")
    return f"sha256:{sha256(raw).hexdigest()}"


def verify_close_pack(
    payload_json: str | bytes,
    expected_storage_hash: str,
    expected_pack_fingerprint: str | None = None,
) -> None:
    """Verify exact stored bytes first, then the canonical pack fingerprint.

    Errors are deliberately collapsed to one safe exception so callers cannot
    disclose corrupted payload contents or parser details.
    """

    try:
        if storage_hash(payload_json) != expected_storage_hash:
            raise ClosePackIntegrityError("close pack storage hash mismatch")
        raw = payload_json.decode("utf-8") if isinstance(payload_json, bytes) else payload_json
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("pack_fingerprint") != pack_fingerprint(payload):
            raise ClosePackIntegrityError("close pack fingerprint mismatch")
        if expected_pack_fingerprint is not None and payload["pack_fingerprint"] != expected_pack_fingerprint:
            raise ClosePackIntegrityError("close pack persisted fingerprint mismatch")
    except ClosePackIntegrityError:
        raise
    except Exception as exc:
        raise ClosePackIntegrityError("close pack payload is invalid") from exc
