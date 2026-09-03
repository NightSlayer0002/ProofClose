from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.domain.enums import Classification, Decision, SubjectType
from app.domain.models import ConfigurationBundle, DecisionMaterial, MatchEvidence, ProofResult, ProofSubject, SourceReference
from app.main import create_app
from app.proofs.fingerprint import fingerprint_material
from app.proofs.registry import RuleRegistry
from app.proofs.service import ProofService
from app.storage.schema import ProofOperationRecord, ProofRecord, RunRecord, SourceSnapshot


def legacy_v1_inputs() -> dict:
    source_rows = [
        {"table": "razorpay_recon", "id": "raw_pay_1", "raw_hash": "sha256:recon"},
        {"table": "settlements", "id": "raw_setl_1", "raw_hash": "sha256:settlement"},
        {"table": "bank_statement", "id": "raw_bank_1", "raw_hash": "sha256:bank"},
    ]
    return {
        "ledger_rows": [
            {
                "tenant_id": "demo",
                "source_id": "src_recon",
                "raw_record_id": "raw_pay_1",
                "entity_id": "pay_1",
                "type": "payment",
                "debit_paise": 0,
                "credit_paise": 100_000,
                "amount_paise": 100_000,
                "fee_paise": 0,
                "tax_paise": 0,
                "settlement_id": "setl_1",
                "settlement_utr": "UTR1",
                "order_id": "order_1",
                "created_at": "2026-08-26T06:00:00Z",
                "settled_at": "2026-08-26T09:00:00Z",
            }
        ],
        "settlement": {
            "tenant_id": "demo",
            "source_id": "src_settlement",
            "raw_record_id": "raw_setl_1",
            "settlement_id": "setl_1",
            "amount_paise": 100_000,
            "status": "processed",
            "utr": "UTR1",
            "fees_paise": 0,
            "tax_paise": 0,
            "created_at": "2026-08-26T07:00:00Z",
        },
        "bank_lines": [
            {
                "tenant_id": "demo",
                "source_id": "src_bank",
                "raw_record_id": "raw_bank_1",
                "bank_ref": "bank_1",
                "utr": "UTR1",
                "credit_amount_paise": 100_000,
                "value_date": "2026-08-26T09:00:00Z",
                "narration": "SETTLEMENT",
            }
        ],
        "now": "2026-08-26T12:00:00+00:00",
        "policy": {"pending_hours": 3, "amount_candidate_window_hours": 48},
        "source_rows": source_rows,
    }


def legacy_v1_material() -> dict:
    inputs = legacy_v1_inputs()
    return {
        "status": "AUTO_VERIFIED",
        "source_rows": inputs["source_rows"],
        "inputs": inputs,
        "formula": "sum(credit_paise) - sum(debit_paise), grouped by settlement_id",
        "result": {"expected_paise": 100_000, "observed_paise": 100_000, "delta_paise": 0},
        "evidence": {
            "utr_exact": True,
            "amount_exact": True,
            "settlement_ledger_consistent": True,
            "temporal_consistency": True,
            "candidate_count": 1,
            "amount_delta_paise": 0,
        },
        "decision_score": 100,
        "decision_reasons": [
            "UTR exact",
            "Amount exact",
            "Settlement reconstruction consistent",
            "Unique bank candidate",
        ],
        "classification": "calculated",
        "exception_type": None,
        "unresolved_reason": None,
    }


def test_create_app_registers_current_and_historical_rules_and_configuration(tmp_path) -> None:
    """Startup must publish exact rule/config versions for current runs and historical reproduction."""
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))

    try:
        settlement_current = app.state.proof_service.registry.current("settlement_match")
        order_current = app.state.proof_service.registry.current("order_payment_consistency")
        configuration = app.state.configuration_registry.current()
    finally:
        app.state.database.dispose()
        app.state.observability.dispose()

    assert app.state.proof_service.registry.resolve("settlement_match", "1.0") is not None
    assert app.state.proof_service.registry.resolve("settlement_match", "2.0") is not None
    assert settlement_current is not None and settlement_current[0] == "2.0"
    assert app.state.proof_service.registry.resolve("order_payment_consistency", "1.0") is not None
    assert order_current is not None and order_current[0] == "1.0"
    assert configuration is not None
    assert configuration.model_dump(mode="json") == {
        "version": "2.0",
        "values": {
            "pending_hours": 3,
            "bank_match_window_hours": 48,
            "early_bank_tolerance_hours": 2,
            "future_clock_skew_minutes": 5,
        },
    }


def test_current_configuration_keeps_canonical_pending_hours_when_setting_is_overridden(tmp_path) -> None:
    """The versioned v2 bundle must not drift with an environment override."""
    app = create_app(
        Settings(
            PROOFCLOSE_ENV="demo",
            PROOFCLOSE_DATA_DIR=tmp_path,
            PROOFCLOSE_BANK_PENDING_HOURS=17,
        )
    )

    try:
        configuration = app.state.configuration_registry.current()
    finally:
        app.state.database.dispose()
        app.state.observability.dispose()

    assert configuration is not None
    assert configuration.values["pending_hours"] == 3


def test_reproduction_failure_does_not_modify_original_proof() -> None:
    """A reproduction failure must remain a separate event, not rewrite financial history."""
    service = ProofService(RuleRegistry(), now=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc))
    evidence = MatchEvidence(
        utr_exact=True,
        amount_exact=True,
        settlement_ledger_consistent=True,
        temporal_consistency=True,
        candidate_count=1,
        amount_delta_paise=0,
    )
    material = DecisionMaterial(
        subject=ProofSubject(subject_type=SubjectType.SETTLEMENT, subject_id="setl_1"),
        rule_name="settlement_match",
        rule_version="9.9",
        configuration=ConfigurationBundle(version="1.0", values={"pending_hours": 3}),
        status=Decision.AUTO_VERIFIED,
        source_rows=(SourceReference(table="bank", id="b1", raw_hash="sha256:a"),),
        evidence_inputs={"observed_credit_paise": 100},
        evaluated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        formula="observed",
        result=ProofResult(expected_paise=100, observed_paise=100, delta_paise=0),
        evidence=evidence,
        decision_score=100,
        decision_reasons=("Unique bank candidate",),
        classification=Classification.CALCULATED,
    )
    proof = service.create("demo", "run_1", "snap_1", "settlement_match", "9.9", "1.0", material)
    before = proof.model_dump(mode="json")
    failure = service.reproduce(proof.proof_id)
    assert failure.failure_type == "RULE_IMPLEMENTATION_UNAVAILABLE"
    assert service.get(proof.proof_id).model_dump(mode="json") == before


def test_historical_v1_reproduction_uses_exact_rule_and_never_falls_back_to_v2(tmp_path) -> None:
    """Removing the original evaluator must fail explicitly rather than silently using the current rule."""
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))
    material = legacy_v1_material()
    payload = {
        "proof_id": "proof_legacy",
        "tenant_id": "demo",
        "run_id": "run_legacy",
        "source_snapshot_id": "snapshot_legacy",
        "rule_name": "settlement_match",
        "rule_version": "1.0",
        "configuration_version": "1.0",
        **material,
        "proof_fingerprint": fingerprint_material(material),
        "supersedes_proof_id": None,
        "created_at": "2026-08-26T12:00:00Z",
    }
    with app.state.database.session() as session:
        session.add(
            SourceSnapshot(
                id="snapshot_legacy",
                tenant_id="demo",
                source_ids_json="[]",
                snapshot_hash="c" * 64,
            )
        )
        session.flush()
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
        session.flush()
        session.add(
            ProofRecord(
                id="proof_legacy",
                tenant_id="demo",
                run_id="run_legacy",
                source_snapshot_id="snapshot_legacy",
                rule_name="settlement_match",
                rule_version="1.0",
                proof_fingerprint=payload["proof_fingerprint"],
                payload_json=__import__("json").dumps(payload),
            )
        )

    try:
        reproduced = app.state.proof_service.reproduce("proof_legacy", tenant_id="demo")
        app.state.proof_service.registry.remove("settlement_match", "1.0")
        missing = app.state.proof_service.reproduce("proof_legacy", tenant_id="demo")
    finally:
        app.state.database.dispose()
        app.state.observability.dispose()

    assert reproduced.status == "REPRODUCED"
    assert reproduced.original_fingerprint == payload["proof_fingerprint"]
    assert reproduced.reproduced_fingerprint == payload["proof_fingerprint"]
    assert missing.status == "FAILED"
    assert missing.failure_type == "RULE_IMPLEMENTATION_UNAVAILABLE"


def test_persisted_proof_can_be_reproduced_after_application_restart(tmp_path) -> None:
    """Proof auditability must survive a process restart, not depend on an in-memory cache."""
    settings = Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path)
    first_app = create_app(settings)
    with TestClient(first_app) as first_client:
        first_client.post("/api/demo/seed")
        run = first_client.post("/api/runs", json={}).json()
        proof_id = first_client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"][0]["proof_id"]
    first_app.state.database.dispose()
    first_app.state.observability.dispose()

    restarted_app = create_app(settings)
    with TestClient(restarted_app, raise_server_exceptions=False) as restarted_client:
        proof_response = restarted_client.get(f"/api/proofs/{proof_id}")
        reproduction_response = restarted_client.post(f"/api/proofs/{proof_id}/reproduce")
        reevaluation_response = restarted_client.post(f"/api/proofs/{proof_id}/reevaluate")
        reevaluated_id = reevaluation_response.json()["proof"]["proof_id"]
    restarted_app.state.database.dispose()
    restarted_app.state.observability.dispose()

    second_restart = create_app(settings)
    with TestClient(second_restart, raise_server_exceptions=False) as second_restart_client:
        reevaluated_response = second_restart_client.get(f"/api/proofs/{reevaluated_id}")
    second_restart.state.database.dispose()
    second_restart.state.observability.dispose()

    assert proof_response.status_code == 200
    assert reproduction_response.status_code == 200
    assert reproduction_response.json()["status"] == "REPRODUCED"
    assert reevaluation_response.status_code == 200
    assert reevaluated_response.status_code == 200
    reevaluated_payload = reevaluated_response.json()
    assert reevaluated_payload.get("supersedes_proof_id") == proof_id, reevaluated_payload


def test_persisted_order_proof_can_be_reproduced_after_application_restart(tmp_path) -> None:
    """Dedicated order proofs must survive restart and reproduce through their exact rule registration."""
    settings = Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path)
    first_app = create_app(settings)
    with TestClient(first_app) as first_client:
        first_client.post("/api/demo/seed")
        run = first_client.post("/api/runs", json={}).json()
        order_item = next(
            item
            for item in first_client.get(f"/api/exceptions?run_id={run['run_id']}").json()["items"]
            if item["exception_type"] == "UNEXPECTED_MULTIPLE_SETTLED_PAYMENTS"
        )
        order_proof_id = order_item["proof_id"]
    first_app.state.database.dispose()
    first_app.state.observability.dispose()

    restarted_app = create_app(settings)
    with TestClient(restarted_app, raise_server_exceptions=False) as restarted_client:
        proof_response = restarted_client.get(f"/api/proofs/{order_proof_id}")
        reproduction_response = restarted_client.post(f"/api/proofs/{order_proof_id}/reproduce")
    restarted_app.state.database.dispose()
    restarted_app.state.observability.dispose()

    assert proof_response.status_code == 200
    assert proof_response.json()["subject"] == {"subject_type": "ORDER", "subject_id": "order_PC0061"}
    assert reproduction_response.status_code == 200
    assert reproduction_response.json()["status"] == "REPRODUCED"


def test_tampered_persisted_proof_fetch_is_sanitized_and_not_cached(tmp_path) -> None:
    settings = Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path)
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        proof_id = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"][0]["proof_id"]
        with app.state.database.session() as session:
            record = session.get(ProofRecord, proof_id)
            assert record is not None
            payload = json.loads(record.payload_json)
            payload["decision_score"] = 1
            record.payload_json = json.dumps(payload)

        fetched = client.get(f"/api/proofs/{proof_id}")
        reproduced = client.post(f"/api/proofs/{proof_id}/reproduce")

    assert fetched.status_code == 409
    assert fetched.json() == {"detail": {"code": "PROOF_INTEGRITY_FAILURE"}}
    assert "decision_score" not in fetched.text
    assert reproduced.status_code == 200
    assert reproduced.json() == {
        "operation": "HISTORICAL_REPRODUCTION",
        "status": "FAILED",
        "failure_type": "PROOF_ARTIFACT_TAMPERED",
        "original_fingerprint": None,
        "reproduced_fingerprint": None,
        "proof": None,
    }

    with app.state.database.session() as session:
        operation = session.scalar(
            select(ProofOperationRecord).where(
                ProofOperationRecord.proof_id == proof_id,
                ProofOperationRecord.operation == "HISTORICAL_REPRODUCTION",
            )
        )
        assert operation is not None
        assert operation.status == "FAILED"
        assert operation.failure_type == "PROOF_ARTIFACT_TAMPERED"

    app.state.database.dispose()
    app.state.observability.dispose()
