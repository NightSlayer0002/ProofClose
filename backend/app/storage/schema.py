from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SourceRecord(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_type", "content_hash", name="uq_source_delivery"),
        Index("ix_sources_tenant_state", "tenant_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_id",
            "source_type",
            "external_id",
            "content_hash",
            name="uq_raw_evidence_delivery",
        ),
        Index("ix_raw_tenant_source", "tenant_id", "source_id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class NormalizedRecord(Base):
    __tablename__ = "normalized_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "raw_record_id", "normalization_version", name="uq_normalized_version"),
        Index("ix_normalized_tenant_type", "tenant_id", "record_type"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    raw_record_id: Mapped[str] = mapped_column(ForeignKey("raw_records.id"), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (UniqueConstraint("tenant_id", "snapshot_hash", name="uq_tenant_snapshot"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class RunRecord(Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (Index("ix_runs_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_snapshot_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(16), nullable=False)
    configuration_version: Mapped[str] = mapped_column(String(16), nullable=False)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    explained_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    total_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    timings_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class ReconciliationRecord(Base):
    __tablename__ = "reconciliation_results"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_id", "settlement_id", name="uq_run_settlement"),
        Index("ix_results_tenant_run", "tenant_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False, index=True)
    settlement_id: Mapped[str] = mapped_column(String(64), nullable=False)
    utr: Mapped[str | None] = mapped_column(String(96))
    expected_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_paise: Mapped[int | None] = mapped_column(Integer)
    difference_paise: Mapped[int | None] = mapped_column(Integer)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    exception_type: Mapped[str | None] = mapped_column(String(64))
    proof_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bank_ref: Mapped[str | None] = mapped_column(String(96))
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False)


class ProofRecord(Base):
    __tablename__ = "proof_objects"
    __table_args__ = (Index("ix_proofs_tenant_run", "tenant_id", "run_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False, index=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(16), nullable=False)
    proof_fingerprint: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class ProofOperationRecord(Base):
    __tablename__ = "proof_operations"
    __table_args__ = (Index("ix_proof_operations_tenant_proof", "tenant_id", "proof_id"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    proof_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_type: Mapped[str | None] = mapped_column(String(64))
    original_fingerprint: Mapped[str | None] = mapped_column(String(80))
    reproduced_fingerprint: Mapped[str | None] = mapped_column(String(80))
    result_proof_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class ExceptionRecord(Base):
    __tablename__ = "exceptions"
    __table_args__ = (Index("ix_exceptions_tenant_run", "tenant_id", "run_id"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False, index=True)
    proof_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exception_type: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), default="OPEN", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class AuditRecord(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_tenant_run", "tenant_id", "run_id"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(96), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_state: Mapped[str] = mapped_column(String(32), nullable=False)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class FeedbackRecord(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    proof_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(96), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(48), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class CloseApprovalRecord(Base):
    __tablename__ = "close_approvals"
    __table_args__ = (UniqueConstraint("tenant_id", "run_id", name="uq_close_approval"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(96), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)


class ClosePackRecord(Base):
    """The single authoritative Final Close Pack for a tenant/run."""

    __tablename__ = "close_packs"
    __table_args__ = (UniqueConstraint("tenant_id", "run_id", name="uq_close_pack"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False, index=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey("close_approvals.id"), nullable=False, unique=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    storage_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    pack_fingerprint: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
