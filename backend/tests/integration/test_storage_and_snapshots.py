import json
from datetime import datetime, timezone

import pytest

from app.domain.enums import Classification, Decision, SubjectType
from app.domain.models import ConfigurationBundle, DecisionMaterial, MatchEvidence, ProofResult, ProofSubject, SourceReference
from app.ingestion.service import IngestionService
from app.proofs.fingerprint import ProofIntegrityError, fingerprint_material
from app.proofs.registry import RuleRegistry
from app.proofs.service import ProofService
from app.storage.database import DatabaseManager
from app.storage.repositories import ProofArtifactRepository, SnapshotRepository, SourceRepository
from app.storage.schema import ProofRecord, RunRecord, SourceSnapshot


BANK_CSV = b"bank_ref,utr,credit_amount_paise,value_date,narration\nbank_1,UTR1,475000,2026-08-26T09:00:00Z,SETTLEMENT\n"


def build_services(tmp_path):
    database = DatabaseManager(f"sqlite:///{(tmp_path / 'proofclose.db').as_posix()}")
    database.create_schema()
    sources = SourceRepository(database)
    snapshots = SnapshotRepository(database)
    ingestion = IngestionService(database, sources)
    return database, sources, snapshots, ingestion


def test_reingesting_identical_file_is_idempotent(tmp_path) -> None:
    """A repeated delivery must not duplicate raw or normalized financial state."""
    database, sources, snapshots, ingestion = build_services(tmp_path)
    first = ingestion.ingest_csv("demo", "bank_statement", "bank.csv", BANK_CSV)
    second = ingestion.ingest_csv("demo", "bank_statement", "bank.csv", BANK_CSV)
    assert first.inserted_rows == 1
    assert second.inserted_rows == 0
    assert second.duplicate_rows == 1
    assert first.source_id == second.source_id


def test_parse_failure_is_quarantined_instead_of_empty_source(tmp_path) -> None:
    """Missing required columns must be explicit evidence failure, not zero transactions."""
    database, sources, snapshots, ingestion = build_services(tmp_path)
    result = ingestion.ingest_csv("demo", "bank_statement", "wrong.csv", b"foo,bar\n1,2\n")
    assert result.state == "QUARANTINED"
    assert result.accepted_rows == 0
    assert result.error == "source bank_statement row 1 field header: unexpected header: bar"


def test_invalid_money_row_is_quarantined_with_a_traceable_source(tmp_path) -> None:
    """A row conversion failure must not vanish as an unrecorded request error."""
    database, sources, snapshots, ingestion = build_services(tmp_path)
    invalid = (
        b"bank_ref,utr,credit_amount_paise,value_date,narration\n"
        b"bank_bad,UTR_BAD,not-money,2026-08-26T09:00:00Z,SETTLEMENT\n"
    )

    result = ingestion.ingest_csv("demo", "bank_statement", "bad-money.csv", invalid)

    assert result.state == "QUARANTINED"
    assert result.accepted_rows == 0
    persisted = sources.get("demo", result.source_id)
    assert persisted is not None
    assert persisted.state == "QUARANTINED"
    assert "row 2" in (result.error or "")


def test_source_repository_denies_cross_tenant_lookup(tmp_path) -> None:
    """Removing the tenant predicate would leak merchant evidence."""
    database, sources, snapshots, ingestion = build_services(tmp_path)
    result = ingestion.ingest_csv("tenant_a", "bank_statement", "bank.csv", BANK_CSV)
    assert sources.get("tenant_a", result.source_id) is not None
    assert sources.get("tenant_b", result.source_id) is None


def test_normalized_field_retains_raw_provenance(tmp_path) -> None:
    """A reviewer must be able to trace canonical paise back to the exact CSV cell."""
    database, sources, snapshots, ingestion = build_services(tmp_path)
    result = ingestion.ingest_csv("demo", "bank_statement", "bank.csv", BANK_CSV)
    rows = sources.list_normalized("demo", result.source_id, "bank_statement")
    provenance = rows[0]["provenance"]["credit_amount_paise"]
    assert provenance == {
        "tenant_id": "demo",
        "source_id": result.source_id,
        "raw_record_id": rows[0]["raw_record_id"],
        "raw_field": "credit_amount_paise",
        "raw_value": "475000",
        "normalized_value": 475000,
        "normalization_version": "1.0",
    }


def test_snapshot_hash_is_stable_and_tenant_scoped(tmp_path) -> None:
    """Snapshot identity must change only with its ordered source evidence set."""
    database, sources, snapshots, ingestion = build_services(tmp_path)
    result = ingestion.ingest_csv("demo", "bank_statement", "bank.csv", BANK_CSV)
    first = snapshots.create("demo", [result.source_id])
    second = snapshots.create("demo", [result.source_id])
    assert first.snapshot_hash == second.snapshot_hash
    assert snapshots.get("other", first.snapshot_id) is None
    assert json.loads(first.source_ids_json) == [result.source_id]


def test_new_cumulative_source_version_keeps_repeated_rows_in_its_snapshot(tmp_path) -> None:
    """An unchanged row repeated in a newer delivery must not disappear from that version."""
    database, sources, snapshots, ingestion = build_services(tmp_path)
    first = ingestion.ingest_csv("demo", "bank_statement", "bank-v1.csv", BANK_CSV)
    second_csv = BANK_CSV + b"bank_2,UTR2,120000,2026-08-26T10:00:00Z,SETTLEMENT\n"
    second = ingestion.ingest_csv("demo", "bank_statement", "bank-v2.csv", second_csv)

    snapshot = snapshots.create("demo", [second.source_id])
    rows = sources.list_snapshot_records(
        "demo",
        json.loads(snapshot.source_ids_json),
        "bank_statement",
    )

    assert first.source_id != second.source_id
    assert {row["bank_ref"] for row in rows} == {"bank_1", "bank_2"}


def test_proof_repository_verifies_v2_artifact_before_returning_it(tmp_path) -> None:
    """A changed stored payload must not reach an API handler as apparently valid financial evidence."""
    database, _sources, _snapshots, _ingestion = build_services(tmp_path)
    repository = ProofArtifactRepository(database)
    with database.session() as session:
        session.add(
            SourceSnapshot(
                id="snapshot_1",
                tenant_id="demo",
                source_ids_json="[]",
                snapshot_hash="a" * 64,
            )
        )
    with database.session() as session:
        session.add(
            RunRecord(
                id="run_1",
                tenant_id="demo",
                source_snapshot_id="snapshot_1",
                state="SUCCESS",
                rule_version="2.0",
                configuration_version="2.0",
                records_processed=0,
                expected_paise=0,
                explained_paise=0,
                unresolved_paise=0,
                total_ms=0,
                timings_json="{}",
            )
        )
    service = ProofService(RuleRegistry(), now=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc))
    material = DecisionMaterial(
        subject=ProofSubject(subject_type=SubjectType.SETTLEMENT, subject_id="setl_1"),
        rule_name="settlement_match",
        rule_version="2.0",
        configuration=ConfigurationBundle(version="2.0", values={"pending_hours": 3}),
        source_rows=(SourceReference(table="bank_statement", id="bank_1", raw_hash="sha256:abc"),),
        evidence_inputs={"settlement": {"amount_paise": 100}},
        evaluated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        status=Decision.AUTO_VERIFIED,
        formula="observed",
        result=ProofResult(expected_paise=100, observed_paise=100, delta_paise=0),
        evidence=MatchEvidence(
            utr_exact=True,
            amount_exact=True,
            settlement_ledger_consistent=True,
            temporal_consistency=True,
            candidate_count=1,
            amount_delta_paise=0,
        ),
        decision_score=100,
        decision_reasons=("Unique bank candidate",),
        classification=Classification.CALCULATED,
    )
    proof = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material)
    repository.save(proof)

    assert repository.get("demo", proof.proof_id) == proof
    with database.session() as session:
        stored = session.get(ProofRecord, proof.proof_id)
        assert stored is not None
        payload = json.loads(stored.payload_json)
        payload["tenant_id"] = "other_tenant"
        stored.payload_json = json.dumps(payload)
    with pytest.raises(ProofIntegrityError):
        repository.get("demo", proof.proof_id)


def test_persisted_v1_proof_reproduces_original_fingerprint_or_fails_for_missing_rule(tmp_path) -> None:
    """A real v1 database row must use its preserved inputs and v1 fingerprint semantics."""
    database, _sources, _snapshots, _ingestion = build_services(tmp_path)
    repository = ProofArtifactRepository(database)
    with database.session() as session:
        session.add(
            SourceSnapshot(
                id="snapshot_legacy",
                tenant_id="demo",
                source_ids_json="[]",
                snapshot_hash="b" * 64,
            )
        )
    with database.session() as session:
        session.add(
            RunRecord(
                id="run_legacy",
                tenant_id="demo",
                source_snapshot_id="snapshot_legacy",
                state="SUCCESS",
                rule_version="1.0",
                configuration_version="1.0",
                records_processed=0,
                expected_paise=0,
                explained_paise=0,
                unresolved_paise=0,
                total_ms=0,
                timings_json="{}",
            )
        )
    legacy_material = {
        "status": "AUTO_VERIFIED",
        "source_rows": [{"table": "bank_statement", "id": "bank_1", "raw_hash": "sha256:abc"}],
        "inputs": {"observed_credit_paise": 100},
        "formula": "observed",
        "result": {"expected_paise": 100, "observed_paise": 100, "delta_paise": 0},
        "evidence": {
            "utr_exact": True,
            "amount_exact": True,
            "settlement_ledger_consistent": True,
            "temporal_consistency": True,
            "candidate_count": 1,
            "amount_delta_paise": 0,
        },
        "decision_score": 100,
        "decision_reasons": ["Unique bank candidate"],
        "classification": "calculated",
        "exception_type": None,
        "unresolved_reason": None,
    }
    legacy_payload = {
        "proof_id": "proof_legacy",
        "tenant_id": "demo",
        "run_id": "run_legacy",
        "source_snapshot_id": "snapshot_legacy",
        "rule_name": "settlement_match",
        "rule_version": "1.0",
        "configuration_version": "1.0",
        **legacy_material,
        "proof_fingerprint": fingerprint_material(legacy_material),
        "supersedes_proof_id": None,
        "created_at": "2026-08-26T12:00:00Z",
    }
    with database.session() as session:
        session.add(
            ProofRecord(
                id="proof_legacy",
                tenant_id="demo",
                run_id="run_legacy",
                source_snapshot_id="snapshot_legacy",
                rule_name="settlement_match",
                rule_version="1.0",
                proof_fingerprint=legacy_payload["proof_fingerprint"],
                payload_json=json.dumps(legacy_payload),
            )
        )

    evaluator_calls: list[dict] = []

    def legacy_evaluator(inputs: dict) -> dict:
        evaluator_calls.append(inputs)
        return legacy_material

    registry = RuleRegistry()
    registry.register("settlement_match", "1.0", legacy_evaluator)
    reproduced = ProofService(registry, store=repository).reproduce("proof_legacy", tenant_id="demo")

    assert reproduced.status == "REPRODUCED"
    assert reproduced.original_fingerprint == legacy_payload["proof_fingerprint"]
    assert reproduced.reproduced_fingerprint == legacy_payload["proof_fingerprint"]
    assert evaluator_calls == [legacy_payload["inputs"]]

    malformed_material = {**legacy_material, "inputs": {"observed_credit_paise": 100, "policy": {"pending_hours": 3}}}
    malformed_payload = {
        **legacy_payload,
        "proof_id": "proof_legacy_malformed",
        **malformed_material,
        "proof_fingerprint": fingerprint_material(malformed_material),
    }
    with database.session() as session:
        session.add(
            ProofRecord(
                id="proof_legacy_malformed",
                tenant_id="demo",
                run_id="run_legacy",
                source_snapshot_id="snapshot_legacy",
                rule_name="settlement_match",
                rule_version="1.0",
                proof_fingerprint=malformed_payload["proof_fingerprint"],
                payload_json=json.dumps(malformed_payload),
            )
        )
    malformed = ProofService(registry, store=repository).reproduce("proof_legacy_malformed", tenant_id="demo")

    assert malformed.status == "FAILED"
    assert malformed.failure_type == "CONFIGURATION_PAYLOAD_INCOMPATIBLE"
    assert evaluator_calls == [legacy_payload["inputs"]]

    missing_registry = RuleRegistry()
    fallback_calls: list[dict] = []

    def current_fallback(inputs: dict) -> dict:
        fallback_calls.append(inputs)
        return legacy_material

    missing_registry.register("settlement_match", "2.0", current_fallback)
    missing_registry.set_current("settlement_match", "2.0")
    missing = ProofService(missing_registry, store=repository).reproduce("proof_legacy", tenant_id="demo")

    assert missing.status == "FAILED"
    assert missing.failure_type == "RULE_IMPLEMENTATION_UNAVAILABLE"
    assert fallback_calls == []
