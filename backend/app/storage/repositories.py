from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import select

from app.domain.models import ProofObject
from app.proofs.legacy import LegacyProofObject, parse_stored_proof
from app.storage.database import DatabaseManager
from app.storage.schema import (
    NormalizedRecord,
    ProofOperationRecord,
    ProofRecord,
    RawRecord,
    SourceRecord,
    SourceSnapshot,
    ClosePackRecord,
)


@dataclass(frozen=True)
class SnapshotView:
    snapshot_id: str
    tenant_id: str
    source_ids_json: str
    snapshot_hash: str


@dataclass(frozen=True)
class ProofRecordIdentity:
    """Trusted identifiers read from proof table columns, never from payload JSON."""

    proof_id: str
    tenant_id: str
    run_id: str


class SourceRepository:
    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def get(self, tenant_id: str, source_id: str) -> SourceRecord | None:
        with self.database.session() as session:
            return session.scalar(
                select(SourceRecord).where(SourceRecord.id == source_id, SourceRecord.tenant_id == tenant_id)
            )

    def list(self, tenant_id: str) -> list[SourceRecord]:
        with self.database.session() as session:
            return list(session.scalars(select(SourceRecord).where(SourceRecord.tenant_id == tenant_id)))

    def list_normalized(self, tenant_id: str, source_id: str, record_type: str) -> list[dict]:
        with self.database.session() as session:
            records = list(
                session.execute(
                    select(NormalizedRecord, RawRecord.content_hash).join(
                        RawRecord, RawRecord.id == NormalizedRecord.raw_record_id
                    ).where(
                        NormalizedRecord.tenant_id == tenant_id,
                        NormalizedRecord.source_id == source_id,
                        NormalizedRecord.record_type == record_type,
                    )
                )
            )
        return [
            {
                **json.loads(record.payload_json),
                "tenant_id": record.tenant_id,
                "source_id": record.source_id,
                "raw_record_id": record.raw_record_id,
                "raw_hash": f"sha256:{raw_hash}",
                "provenance": json.loads(record.provenance_json),
            }
            for record, raw_hash in records
        ]

    def list_snapshot_records(self, tenant_id: str, source_ids: list[str], record_type: str) -> list[dict]:
        with self.database.session() as session:
            records = list(
                session.execute(
                    select(NormalizedRecord, RawRecord.content_hash).join(
                        RawRecord, RawRecord.id == NormalizedRecord.raw_record_id
                    ).where(
                        NormalizedRecord.tenant_id == tenant_id,
                        NormalizedRecord.source_id.in_(source_ids),
                        NormalizedRecord.record_type == record_type,
                    )
                )
            )
        return [
            {
                **json.loads(record.payload_json),
                "tenant_id": record.tenant_id,
                "source_id": record.source_id,
                "raw_record_id": record.raw_record_id,
                "raw_hash": f"sha256:{raw_hash}",
                "provenance": json.loads(record.provenance_json),
            }
            for record, raw_hash in records
        ]


class SnapshotRepository:
    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def create(self, tenant_id: str, source_ids: list[str]) -> SnapshotView:
        ordered = sorted(dict.fromkeys(source_ids))
        payload = json.dumps(ordered, separators=(",", ":"))
        snapshot_hash = sha256(payload.encode("utf-8")).hexdigest()
        snapshot_id = f"snapshot_{snapshot_hash[:20]}"
        with self.database.session() as session:
            selected = list(
                session.execute(
                    select(SourceRecord.id, SourceRecord.source_type).where(
                        SourceRecord.tenant_id == tenant_id,
                        SourceRecord.id.in_(ordered),
                        SourceRecord.state == "ACCEPTED",
                    )
                )
            )
            owned = {source_id for source_id, _source_type in selected}
            if owned != set(ordered):
                raise ValueError("snapshot contains missing, quarantined, or cross-tenant sources")
            source_types = [source_type for _source_id, source_type in selected]
            if len(source_types) != len(set(source_types)):
                raise ValueError("snapshot must select at most one version of each source type")
            existing = session.scalar(
                select(SourceSnapshot).where(
                    SourceSnapshot.tenant_id == tenant_id, SourceSnapshot.snapshot_hash == snapshot_hash
                )
            )
            if existing is None:
                existing = SourceSnapshot(
                    id=snapshot_id,
                    tenant_id=tenant_id,
                    source_ids_json=payload,
                    snapshot_hash=snapshot_hash,
                )
                session.add(existing)
        return SnapshotView(existing.id, existing.tenant_id, existing.source_ids_json, existing.snapshot_hash)

    def get(self, tenant_id: str, snapshot_id: str) -> SnapshotView | None:
        with self.database.session() as session:
            record = session.scalar(
                select(SourceSnapshot).where(
                    SourceSnapshot.id == snapshot_id, SourceSnapshot.tenant_id == tenant_id
                )
            )
            if record is None:
                return None
            return SnapshotView(record.id, record.tenant_id, record.source_ids_json, record.snapshot_hash)

    def latest(self, tenant_id: str) -> SnapshotView | None:
        with self.database.session() as session:
            record = session.scalar(
                select(SourceSnapshot)
                .where(SourceSnapshot.tenant_id == tenant_id)
                .order_by(SourceSnapshot.created_at.desc())
            )
            if record is None:
                return None
            return SnapshotView(record.id, record.tenant_id, record.source_ids_json, record.snapshot_hash)


class ProofArtifactRepository:
    """Durable Proof Objects and lifecycle operations, always loaded through tenant scope."""

    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def get(self, tenant_id: str, proof_id: str) -> ProofObject | LegacyProofObject | None:
        with self.database.session() as session:
            record = session.scalar(
                select(ProofRecord).where(ProofRecord.id == proof_id, ProofRecord.tenant_id == tenant_id)
            )
            return parse_stored_proof(record.payload_json) if record else None

    def get_identity(self, tenant_id: str, proof_id: str) -> ProofRecordIdentity | None:
        """Load only trusted row identity for recording a failed lifecycle attempt."""
        with self.database.session() as session:
            record = session.scalar(
                select(ProofRecord).where(ProofRecord.id == proof_id, ProofRecord.tenant_id == tenant_id)
            )
            if record is None:
                return None
            return ProofRecordIdentity(record.id, record.tenant_id, record.run_id)

    def list_for_run(self, tenant_id: str, run_id: str) -> list[ProofObject | LegacyProofObject]:
        """List and parse only durable proofs owned by the requested tenant/run."""
        with self.database.session() as session:
            records = list(
                session.scalars(
                    select(ProofRecord).where(
                        ProofRecord.tenant_id == tenant_id,
                        ProofRecord.run_id == run_id,
                    )
                )
            )
        return [parse_stored_proof(record.payload_json) for record in records]

    def save(self, proof: ProofObject) -> None:
        with self.database.session() as session:
            existing = session.scalar(
                select(ProofRecord).where(
                    ProofRecord.id == proof.proof_id,
                    ProofRecord.tenant_id == proof.tenant_id,
                )
            )
            if existing:
                if existing.proof_fingerprint != proof.proof_fingerprint:
                    raise ValueError("persisted proof fingerprint conflict")
                return
            session.add(
                ProofRecord(
                    id=proof.proof_id,
                    tenant_id=proof.tenant_id,
                    run_id=proof.run_id,
                    source_snapshot_id=proof.source_snapshot_id,
                    rule_name=proof.rule_name,
                    rule_version=proof.rule_version,
                    proof_fingerprint=proof.proof_fingerprint,
                    payload_json=proof.model_dump_json(),
                )
            )

    def record_operation(self, proof: object, operation: str, result: object) -> None:
        payload = result.model_dump(mode="json")
        result_proof = payload.get("proof")
        with self.database.session() as session:
            session.add(
                ProofOperationRecord(
                    id=f"proofop_{uuid4().hex[:18]}",
                    tenant_id=proof.tenant_id,
                    run_id=proof.run_id,
                    proof_id=proof.proof_id,
                    operation=operation,
                    status=payload["status"],
                    failure_type=payload.get("failure_type"),
                    original_fingerprint=payload.get("original_fingerprint"),
                    reproduced_fingerprint=payload.get("reproduced_fingerprint"),
                    result_proof_id=result_proof.get("proof_id") if result_proof else None,
                )
            )

    def count_failed_operations(self, tenant_id: str, run_id: str) -> int:
        with self.database.session() as session:
            return len(
                list(
                    session.scalars(
                        select(ProofOperationRecord.id).where(
                            ProofOperationRecord.tenant_id == tenant_id,
                            ProofOperationRecord.run_id == run_id,
                            ProofOperationRecord.status == "FAILED",
                        )
                    )
                )
            )


class ClosePackRepository:
    """Tenant-scoped persistence helper for the immutable Final pack."""

    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def get(self, tenant_id: str, run_id: str) -> ClosePackRecord | None:
        with self.database.session() as session:
            return session.scalar(
                select(ClosePackRecord).where(
                    ClosePackRecord.tenant_id == tenant_id,
                    ClosePackRecord.run_id == run_id,
                )
            )

    def get_in_session(self, session, tenant_id: str, run_id: str) -> ClosePackRecord | None:
        return session.scalar(
            select(ClosePackRecord).where(
                ClosePackRecord.tenant_id == tenant_id,
                ClosePackRecord.run_id == run_id,
            )
        )

    def replace_payload_for_test(self, tenant_id: str, run_id: str, payload_json: str) -> None:
        """Test-only tamper seam; production code never rewrites a pack."""
        with self.database.session() as session:
            row = self.get_in_session(session, tenant_id, run_id)
            if row is None:
                raise KeyError(run_id)
            row.payload_json = payload_json
