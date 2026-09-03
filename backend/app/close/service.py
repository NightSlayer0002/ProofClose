"""Approval-gated close state and immutable close-pack lifecycle."""

from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.close.integrity import ClosePackIntegrityError, canonical_pack_json, pack_fingerprint, storage_hash, verify_close_pack
from app.domain.models import ProofObject
from app.proofs.fingerprint import verify_artifact_fingerprint
from app.proofs.legacy import LegacyProofObject, parse_stored_proof
from app.storage.database import DatabaseManager
from app.storage.schema import AuditRecord, CloseApprovalRecord, ClosePackRecord, ExceptionRecord, ProofRecord, ReconciliationRecord, RunRecord, SourceRecord, SourceSnapshot
from app.reconciliation.rules import ORDER_RULE_NAME, ORDER_RULE_VERSION_V1, SETTLEMENT_RULE_NAME


REVIEWED_EXCEPTION_STATES = {"APPROVED", "REJECTED", "LEFT_UNRESOLVED"}


def _iso_utc(value: datetime) -> str:
    """Make SQLite's naive round-trip and live aware values serialize identically."""
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class CloseService:
    def __init__(self, database: DatabaseManager, configuration_registry=None) -> None:
        self.database = database
        self.configuration_registry = configuration_registry

    def _verified_proofs(self, session, tenant_id: str, run_id: str) -> tuple[list[ProofObject | LegacyProofObject], int]:
        records = list(session.scalars(select(ProofRecord).where(ProofRecord.tenant_id == tenant_id, ProofRecord.run_id == run_id)))
        proofs: list[ProofObject | LegacyProofObject] = []
        failures = 0
        for record in records:
            try:
                proof = parse_stored_proof(record.payload_json)
                if isinstance(proof, ProofObject):
                    verify_artifact_fingerprint(proof.model_dump(mode="python"))
                else:
                    proof.verify_original_decision_fingerprint()
                proofs.append(proof)
            except Exception:
                failures += 1
        return proofs, failures

    def _get_state_in_session(self, session, tenant_id: str, run_id: str) -> dict[str, Any]:
        run = session.scalar(select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id))
        if run is None:
            raise KeyError(run_id)
        exceptions = list(session.scalars(select(ExceptionRecord).where(ExceptionRecord.tenant_id == tenant_id, ExceptionRecord.run_id == run_id)))
        proofs, integrity_blockers = self._verified_proofs(session, tenant_id, run_id)
        # Look up by run id after validating the run tenant.  This makes a
        # direct mutation of the durable pack tenant metadata observable as an
        # integrity blocker instead of silently making the Final pack vanish.
        pack = self._find_pack_for_run(session, tenant_id, run_id)
        if pack is not None:
            try:
                self._verify_persisted_pack(session, pack, tenant_id, run_id)
            except ClosePackIntegrityError:
                integrity_blockers += 1
        proof_by_id = {proof.proof_id: proof for proof in proofs}
        settlement_subjects: set[str] = set()
        for item in exceptions:
            proof = proof_by_id.get(item.proof_id)
            subject = getattr(getattr(proof, "subject", None), "subject_id", None)
            kind = getattr(getattr(proof, "subject", None), "subject_type", None)
            if getattr(kind, "value", kind) == "SETTLEMENT":
                settlement_subjects.add(subject or item.proof_id)
        results = list(session.scalars(select(ReconciliationRecord).where(ReconciliationRecord.tenant_id == tenant_id, ReconciliationRecord.run_id == run_id)))
        automatic = sum(item.decision == "AUTO_VERIFIED" for item in results)
        open_count = sum(item.state == "OPEN" for item in exceptions)
        exception_proof_ids = {item.proof_id for item in exceptions}
        unreviewable_count = sum(
            item.decision != "AUTO_VERIFIED" and item.proof_id not in exception_proof_ids
            for item in results
        )
        system_blockers = int(run.state != "SUCCESS")
        total_blockers = open_count + unreviewable_count + system_blockers + integrity_blockers
        if total_blockers:
            state = "BLOCKED"
        elif pack is not None:
            state = "APPROVED_WITH_EXCEPTIONS" if exceptions else "APPROVED_CLEAN"
        elif exceptions:
            state = "REVIEWED_WITH_EXCEPTIONS"
        else:
            state = "READY"
        return {
            "run_id": run_id,
            "state": state,
            "reconciled_paise": run.explained_paise,
            "unresolved_paise": run.unresolved_paise,
            "auto_verified_count": automatic,
            "manually_reviewed_count": len(exceptions) - open_count,
            "blocking_exceptions": total_blockers,
            "unreviewable_blockers": unreviewable_count,
            "exception_count": len(exceptions),
            "settlement_exception_count": len(settlement_subjects),
            "review_item_count": len(exceptions),
            "total_close_blockers": total_blockers,
            "system_error_blockers": system_blockers,
            "integrity_blockers": integrity_blockers,
            "source_snapshot_id": run.source_snapshot_id,
            "rule_version": run.rule_version,
            "configuration_version": run.configuration_version,
        }

    def get_state(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            return self._get_state_in_session(session, tenant_id, run_id)

    def _source_manifest(self, session, tenant_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.id == snapshot_id, SourceSnapshot.tenant_id == tenant_id))
        if snapshot is None:
            raise ClosePackIntegrityError("source snapshot is unavailable")
        source_ids = json.loads(snapshot.source_ids_json)
        sources = list(session.scalars(select(SourceRecord).where(SourceRecord.tenant_id == tenant_id, SourceRecord.id.in_(source_ids))))
        by_id = {row.id: row for row in sources}
        if set(by_id) != set(source_ids):
            raise ClosePackIntegrityError("source delivery is unavailable")
        return {
            "id": snapshot.id,
            "hash": snapshot.snapshot_hash,
            "source_deliveries": [{"source_id": source_id, "content_hash": by_id[source_id].content_hash} for source_id in source_ids],
        }

    @staticmethod
    def _proof_payload(proof: ProofObject | LegacyProofObject) -> dict[str, Any]:
        if isinstance(proof, ProofObject):
            return {
                "proof_id": proof.proof_id,
                "subject": proof.subject.model_dump(mode="json"),
                "status": proof.status.value,
                "decision_fingerprint": proof.decision_fingerprint,
                "artifact_fingerprint": proof.artifact_fingerprint,
                "rule": {"name": proof.rule_name, "version": proof.rule_version},
                "configuration": {"version": proof.configuration.version, "values": proof.configuration.values.as_dict()},
                "source_rows": [row.model_dump(mode="json") for row in proof.source_rows],
            }
        return {
            "proof_id": proof.proof_id,
            "subject": {"type": "UNKNOWN", "id": proof.proof_id},
            "status": proof.decision.status.value,
            "decision_fingerprint": proof.proof_fingerprint,
            "artifact_fingerprint": None,
            "rule": {"name": proof.rule_name, "version": proof.rule_version},
        }

    def _build_pack_in_session(self, session, tenant_id: str, run_id: str, state: dict[str, Any], approval: CloseApprovalRecord | None, final: bool) -> tuple[dict[str, Any], bytes]:
        run = session.scalar(select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id))
        if run is None:
            raise KeyError(run_id)
        proofs, failures = self._verified_proofs(session, tenant_id, run_id)
        if failures:
            raise PermissionError("tampered proof artifacts block close export")
        exceptions = list(session.scalars(select(ExceptionRecord).where(ExceptionRecord.tenant_id == tenant_id, ExceptionRecord.run_id == run_id).order_by(ExceptionRecord.created_at, ExceptionRecord.id)))
        audits = list(session.scalars(select(AuditRecord).where(AuditRecord.tenant_id == tenant_id, AuditRecord.run_id == run_id).order_by(AuditRecord.created_at, AuditRecord.id)))
        payload: dict[str, Any] = {
            "schema_version": "proofclose-close-pack/v2",
            "pack_state": "FINAL" if final else "DRAFT",
            "immutable": final,
            "mutable": not final,
            "tenant_id": tenant_id,
            "run_id": run_id,
            "totals": {"records_processed": run.records_processed, "expected_paise": run.expected_paise, "explained_paise": run.explained_paise, "unresolved_paise": run.unresolved_paise},
            "settlement_exception_count": state["settlement_exception_count"],
            "review_item_count": state["review_item_count"],
            "total_close_blockers": state["total_close_blockers"],
            "source_snapshot": self._source_manifest(session, tenant_id, run.source_snapshot_id),
            "proofs": [self._proof_payload(proof) for proof in proofs],
            "review_items": [{"exception_id": item.id, "proof_id": item.proof_id, "exception_type": item.exception_type, "amount_paise": item.amount_paise, "state": item.state} for item in exceptions],
            "audit": [{"audit_id": item.id, "actor_id": item.actor_id, "item_id": item.object_id, "previous_state": item.previous_state, "new_state": item.new_state, "reason": item.reason, "created_at": _iso_utc(item.created_at)} for item in audits],
            "rule": {"name": SETTLEMENT_RULE_NAME, "version": run.rule_version, "settlement_version": run.rule_version},
        }
        if self.configuration_registry is None:
            raise ClosePackIntegrityError("configuration registry is unavailable")
        configuration = self.configuration_registry.resolve(run.configuration_version)
        if configuration is None:
            raise ClosePackIntegrityError("configuration values are unavailable")
        payload["configuration"] = {"version": configuration.version, "values": configuration.values.as_dict()}
        rules = {f"{SETTLEMENT_RULE_NAME}@{run.rule_version}", f"{ORDER_RULE_NAME}@{ORDER_RULE_VERSION_V1}"}
        if proofs:
            rules.update(f"{proof.rule_name}@{proof.rule_version}" for proof in proofs)
        payload["rules"] = sorted(rules)
        if approval is not None:
            payload["approval"] = {"approval_id": approval.id, "actor_id": approval.actor_id, "state": approval.state, "reason": approval.reason, "created_at": _iso_utc(approval.created_at)}
        payload["pack_fingerprint"] = pack_fingerprint(payload)
        raw = canonical_pack_json(payload)
        return payload, raw

    @staticmethod
    def _verify_persisted_pack(session, pack: ClosePackRecord, tenant_id: str, run_id: str) -> None:
        """Authenticate both the pack bytes and its database identity metadata."""
        verify_close_pack(pack.payload_json, pack.storage_hash, pack.pack_fingerprint)
        try:
            payload = json.loads(pack.payload_json)
            embedded_approval = payload.get("approval")
            approval = session.scalar(select(CloseApprovalRecord).where(CloseApprovalRecord.id == pack.approval_id))
        except Exception as exc:
            raise ClosePackIntegrityError("close pack metadata is invalid") from exc
        if (
            pack.tenant_id != tenant_id
            or pack.run_id != run_id
            or payload.get("tenant_id") != tenant_id
            or payload.get("run_id") != run_id
            or not isinstance(embedded_approval, dict)
            or embedded_approval.get("approval_id") != pack.approval_id
            or approval is None
            or approval.tenant_id != tenant_id
            or approval.run_id != run_id
            or embedded_approval.get("actor_id") != approval.actor_id
            or embedded_approval.get("reason") != approval.reason
            or embedded_approval.get("state") != approval.state
            or embedded_approval.get("created_at") != _iso_utc(approval.created_at)
        ):
            raise ClosePackIntegrityError("close pack identity metadata mismatch")

    @staticmethod
    def _find_pack_for_run(session, tenant_id: str, run_id: str) -> ClosePackRecord | None:
        pack = session.scalar(select(ClosePackRecord).where(ClosePackRecord.run_id == run_id))
        if pack is not None:
            return pack
        # A mutated row run_id remains discoverable through its immutable
        # approval linkage, so it can be reported as tampered rather than
        # silently treated as an unapproved run.
        return session.scalar(
            select(ClosePackRecord)
            .join(CloseApprovalRecord, CloseApprovalRecord.id == ClosePackRecord.approval_id)
            .where(CloseApprovalRecord.tenant_id == tenant_id, CloseApprovalRecord.run_id == run_id)
        )

    @staticmethod
    def _approval_response(approval: CloseApprovalRecord, state: dict[str, Any], replay: bool) -> dict[str, Any]:
        return {**state, "state": approval.state, "approval_id": approval.id, "actor_id": approval.actor_id, "reason": approval.reason, "approved_at": _iso_utc(approval.created_at), "idempotent_replay": replay}

    def approve(self, tenant_id: str, run_id: str, actor_id: str, reason: str) -> dict[str, Any]:
        cleaned = reason.strip()
        if sum(1 for char in cleaned if char.isprintable() and not char.isspace()) < 5:
            raise ValueError("close approval reason must contain at least five visible characters")
        with self.database.session() as session:
            if session.scalar(select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id)) is None:
                raise KeyError(run_id)
            approval = session.scalar(select(CloseApprovalRecord).where(CloseApprovalRecord.tenant_id == tenant_id, CloseApprovalRecord.run_id == run_id))
            pack = self._find_pack_for_run(session, tenant_id, run_id)
            if pack is not None:
                try:
                    self._verify_persisted_pack(session, pack, tenant_id, run_id)
                except ClosePackIntegrityError:
                    self._record_integrity_event(tenant_id, run_id, pack.id)
                    raise
                if approval is None or pack.approval_id != approval.id:
                    self._record_integrity_event(tenant_id, run_id, pack.id)
                    raise ClosePackIntegrityError("close pack approval linkage is invalid")
            state = self._get_state_in_session(session, tenant_id, run_id)
            if approval is not None:
                if pack is None:
                    raise ClosePackIntegrityError("approval has no Final Close Pack")
                return self._approval_response(approval, state, True)
            if state["state"] not in {"READY", "REVIEWED_WITH_EXCEPTIONS"}:
                raise PermissionError("close is blocked until all blockers are resolved")
            approval = CloseApprovalRecord(id=f"close_{uuid4().hex[:18]}", tenant_id=tenant_id, run_id=run_id, actor_id=actor_id, state="APPROVED_WITH_EXCEPTIONS" if state["review_item_count"] else "APPROVED_CLEAN", reason=cleaned)
            session.add(approval)
            session.flush()
            payload, raw = self._build_pack_in_session(session, tenant_id, run_id, state, approval, True)
            session.add(ClosePackRecord(id=f"pack_{uuid4().hex[:18]}", tenant_id=tenant_id, run_id=run_id, approval_id=approval.id, payload_json=raw.decode("utf-8"), storage_hash=storage_hash(raw), pack_fingerprint=payload["pack_fingerprint"]))
            session.flush()
            return self._approval_response(approval, state, False)

    def approve_with_exceptions(self, tenant_id: str, run_id: str, actor_id: str, reason: str) -> dict[str, Any]:
        return self.approve(tenant_id, run_id, actor_id, reason)

    def _record_integrity_event(self, tenant_id: str, run_id: str, pack_id: str) -> None:
        with self.database.session() as session:
            session.add(AuditRecord(id=f"audit_{uuid4().hex[:18]}", tenant_id=tenant_id, run_id=run_id, actor_id="system", object_type="CLOSE_PACK_INTEGRITY", object_id=pack_id, previous_state="VALID", new_state="TAMPERED", reason="Close pack integrity verification failed"))

    def export_pack(self, tenant_id: str, run_id: str) -> tuple[bytes, str]:
        with self.database.session() as session:
            run = session.scalar(select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id))
            if run is None:
                raise KeyError(run_id)
            pack = self._find_pack_for_run(session, tenant_id, run_id)
            if pack is not None:
                try:
                    self._verify_persisted_pack(session, pack, tenant_id, run_id)
                except ClosePackIntegrityError:
                    self._record_integrity_event(tenant_id, run_id, pack.id)
                    raise
                return pack.payload_json.encode("utf-8"), "FINAL"
            state = self._get_state_in_session(session, tenant_id, run_id)
            if state["total_close_blockers"]:
                raise PermissionError("close is blocked until all blockers are resolved")
            _payload, raw = self._build_pack_in_session(session, tenant_id, run_id, state, None, False)
            return raw, "DRAFT"
