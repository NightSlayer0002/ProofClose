"""Focused contract tests for canonical close-pack integrity primitives."""

import json
from datetime import timezone

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from app.close.integrity import ClosePackIntegrityError, pack_fingerprint, storage_hash, verify_close_pack
from app.storage.schema import AuditRecord, CloseApprovalRecord, ClosePackRecord, ExceptionRecord, ProofRecord, ReconciliationRecord, RunRecord
from test_investigate_review_close import initialized_client


def _pack() -> dict:
    payload = {
        "schema_version": "proofclose-close-pack/v2",
        "pack_state": "FINAL",
        "immutable": True,
        "mutable": False,
        "tenant_id": "tenant-a",
        "run_id": "run-a",
        "totals": {"unresolved_paise": 0},
    }
    payload["pack_fingerprint"] = pack_fingerprint(payload)
    return payload


def test_close_pack_verifies_canonical_fingerprint_and_exact_storage_bytes() -> None:
    raw = json.dumps(_pack(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    verify_close_pack(raw, storage_hash(raw), _pack()["pack_fingerprint"])


def test_close_pack_rejects_persisted_fingerprint_column_mutation() -> None:
    payload = _pack()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    with pytest.raises(ClosePackIntegrityError):
        verify_close_pack(raw, storage_hash(raw), "sha256:tampered")


@pytest.mark.parametrize("mutation", ["pack_fingerprint", "payload"])
def test_close_pack_mutations_fail_closed(mutation: str) -> None:
    payload = _pack()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if mutation == "pack_fingerprint":
        payload["pack_fingerprint"] = "sha256:tampered"
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        expected_hash = storage_hash(raw)
    else:
        expected_hash = storage_hash(raw)
        raw = raw.replace(b'"FINAL"', b'"DRAFT"')
    with pytest.raises(ClosePackIntegrityError):
        verify_close_pack(raw, expected_hash)


def _make_approvable(client: TestClient) -> None:
    """Make the deterministic fixture an explicitly reviewed, zero-delta close."""
    database = client.app.state.database
    with database.session() as session:
        run = session.scalar(select(RunRecord).where(RunRecord.id == client.run_id))
        run.unresolved_paise = 0
        for result in session.scalars(select(ReconciliationRecord).where(ReconciliationRecord.run_id == client.run_id)):
            result.decision = "AUTO_VERIFIED"
        for exception in session.scalars(select(ExceptionRecord).where(ExceptionRecord.run_id == client.run_id)):
            exception.state = "LEFT_UNRESOLVED"


def _make_reviewed_approvable(client: TestClient) -> None:
    """Create a clean-money run whose business review history is real API history."""
    _make_approvable(client)
    with client.app.state.database.session() as session:
        for exception in session.scalars(select(ExceptionRecord).where(ExceptionRecord.run_id == client.run_id)):
            exception.state = "OPEN"
    for item in client.get("/api/exceptions", params={"run_id": client.run_id}).json()["items"]:
        response = client.post(
            f"/api/exceptions/{item['exception_id']}/review",
            json={"action": "APPROVE", "reason": "Confirmed by controller"},
        )
        assert response.status_code == 200


def test_persisted_row_fingerprint_mutation_blocks_export_and_approval(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_approvable(client)
        approved = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Reviewed close"})
        assert approved.status_code == 200
        final_bytes = client.get(f"/api/close/export?run_id={client.run_id}").content
        final_payload = json.loads(final_bytes)
        assert final_payload["schema_version"] == "proofclose-close-pack/v2"
        assert final_payload["pack_state"] == "FINAL"
        assert final_payload["immutable"] is True
        assert final_payload["rules"] == ["order_payment_consistency@1.0", "settlement_match@2.0"]
        assert final_payload["configuration"] == {
            "version": "2.0",
            "values": {
                "pending_hours": 3,
                "bank_match_window_hours": 48,
                "early_bank_tolerance_hours": 2,
                "future_clock_skew_minutes": 5,
            },
        }
        with client.app.state.database.session() as session:
            pack = session.scalar(select(ClosePackRecord).where(ClosePackRecord.run_id == client.run_id))
            pack.pack_fingerprint = "sha256:tampered"
        close = client.get(f"/api/close?run_id={client.run_id}").json()
        assert close["integrity_blockers"] == 1
        exported = client.get(f"/api/close/export?run_id={client.run_id}")
        assert exported.status_code == 409
        assert exported.json()["detail"] == {"code": "CLOSE_PACK_INTEGRITY_FAILURE"}
        replay = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Another reason"})
        assert replay.status_code == 409
        assert replay.json()["detail"] == {"code": "CLOSE_PACK_INTEGRITY_FAILURE"}
        audit = client.get(f"/api/audit?run_id={client.run_id}").json()["items"]
        assert audit[-1]["object_type"] == "CLOSE_PACK_INTEGRITY"
        assert audit[-1]["actor_id"] == "system"
    finally:
        client.__exit__(None, None, None)


def test_draft_is_mutable_and_final_bytes_are_replayed_exactly(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_approvable(client)
        draft, draft_state = client.app.state.close_service.export_pack("demo_merchant", client.run_id)
        assert draft_state == "DRAFT"
        draft_payload = json.loads(draft)
        assert draft_payload["schema_version"] == "proofclose-close-pack/v2"
        assert draft_payload["pack_state"] == "DRAFT"
        assert draft_payload["mutable"] is True
        assert draft_payload["immutable"] is False
        with client.app.state.database.session() as session:
            assert session.scalar(select(ClosePackRecord).where(ClosePackRecord.run_id == client.run_id)) is None
        approval = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Reviewed close"}).json()
        first = client.get(f"/api/close/export?run_id={client.run_id}").content
        replay = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Different operator reason"}).json()
        second = client.get(f"/api/close/export?run_id={client.run_id}").content
        assert first == second
        assert replay["idempotent_replay"] is True
        assert replay["approval_id"] == approval["approval_id"]
        assert replay["actor_id"] == approval["actor_id"]
        assert replay["reason"] == approval["reason"]
    finally:
        client.__exit__(None, None, None)


def test_unknown_configuration_cannot_be_fabricated_into_a_pack(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_approvable(client)
        with client.app.state.database.session() as session:
            run = session.scalar(select(RunRecord).where(RunRecord.id == client.run_id))
            run.configuration_version = "9.9"
        with pytest.raises(ClosePackIntegrityError):
            client.app.state.close_service.export_pack("demo_merchant", client.run_id)
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("action", ["APPROVE", "REJECT", "LEAVE_UNRESOLVED"])
def test_each_legal_review_transition_is_append_only(tmp_path, action: str) -> None:
    client = initialized_client(tmp_path)
    try:
        exception = client.get(f"/api/exceptions?run_id={client.run_id}").json()["items"][0]
        response = client.post(
            f"/api/exceptions/{exception['exception_id']}/review",
            json={"action": action, "reason": "Visible operator reason"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["actor_id"] == "demo_operator"
        assert body["exception_id"] == exception["exception_id"]
        assert body["previous_state"] == "OPEN"
        assert body["reason"] == "Visible operator reason"
        with client.app.state.database.session() as session:
            audit = session.scalar(select(AuditRecord).where(AuditRecord.id == body["audit_id"]))
            assert audit.tenant_id == "demo_merchant"
            assert audit.run_id == client.run_id
            assert audit.object_type == "EXCEPTION"
            assert audit.object_id == exception["exception_id"]
            assert audit.previous_state == "OPEN"
            assert audit.new_state == body["new_state"]
            assert audit.actor_id == "demo_operator"
            assert audit.reason == "Visible operator reason"
    finally:
        client.__exit__(None, None, None)


def test_review_rejects_control_only_reason_and_repeated_transition(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        exception = client.get(f"/api/exceptions?run_id={client.run_id}").json()["items"][0]
        bad = client.post(
            f"/api/exceptions/{exception['exception_id']}/review",
            json={"action": "APPROVE", "reason": "\u200b\u200b\u200b\u200b\u200b\u200b"},
        )
        assert bad.status_code == 422
        assert bad.json()["detail"]["code"] == "INVALID_REQUEST"
        first = client.post(
            f"/api/exceptions/{exception['exception_id']}/review",
            json={"action": "APPROVE", "reason": "Visible operator reason"},
        )
        assert first.status_code == 200
        repeated = client.post(
            f"/api/exceptions/{exception['exception_id']}/review",
            json={"action": "REJECT", "reason": "Second operator reason"},
        )
        assert repeated.status_code == 422
        assert repeated.json()["detail"]["code"] == "INVALID_REVIEW"
    finally:
        client.__exit__(None, None, None)


def test_tampered_proof_blocks_close_approval(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        with client.app.state.database.session() as session:
            proof = session.scalar(select(ProofRecord).where(ProofRecord.run_id == client.run_id))
            proof.payload_json = proof.payload_json.replace('"status":"', '"status":"tampered-')
        response = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Reviewed close"})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CLOSE_POLICY_BLOCKED"
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("reason", ["\x00\x01\x02\x03\x04\x05", " \t\n\r\v\f "])
def test_control_only_close_reason_is_rejected(tmp_path, reason: str) -> None:
    client = initialized_client(tmp_path)
    try:
        response = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": reason})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "INVALID_REQUEST"
    finally:
        client.__exit__(None, None, None)


def test_close_counts_use_distinct_subjects_and_keep_order_excess_out_of_unresolved(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        before = client.get("/api/close", params={"run_id": client.run_id}).json()
        assert before["settlement_exception_count"] == 4
        assert before["review_item_count"] == 5
        assert before["total_close_blockers"] == 6
        unresolved = before["unresolved_paise"]
        exception_items = client.get("/api/exceptions", params={"run_id": client.run_id}).json()["items"]
        order_item = exception_items[-1]
        settlement_item = exception_items[0]
        assert order_item["exception_type"] == "UNEXPECTED_MULTIPLE_SETTLED_PAYMENTS"
        with client.app.state.database.session() as session:
            settlement_proof = session.scalar(
                select(ProofRecord).where(ProofRecord.id == settlement_item["proof_id"])
            )
            session.add(
                ExceptionRecord(
                    id="exc_duplicate_subject",
                    tenant_id="demo_merchant",
                    run_id=client.run_id,
                    proof_id=settlement_proof.id,
                    exception_type="SECONDARY_BUSINESS_EXCEPTION",
                    amount_paise=17,
                    state="OPEN",
                )
            )
        after = client.get("/api/close", params={"run_id": client.run_id}).json()
        assert after["settlement_exception_count"] == 4
        assert after["review_item_count"] == 6
        assert after["total_close_blockers"] == 7
        assert after["unresolved_paise"] == unresolved
        duplicate = client.get("/api/exceptions", params={"run_id": client.run_id}).json()["items"][-1]
        reviewed = client.post(
            f"/api/exceptions/{duplicate['exception_id']}/review",
            json={"action": "APPROVE", "reason": "Confirmed duplicate"},
        )
        assert reviewed.status_code == 200
        reviewed_state = client.get("/api/close", params={"run_id": client.run_id}).json()
        assert reviewed_state["review_item_count"] == 6
        assert reviewed_state["total_close_blockers"] == 6
        assert reviewed_state["unresolved_paise"] == unresolved
        with client.app.state.database.session() as session:
            run = session.scalar(select(RunRecord).where(RunRecord.id == client.run_id))
            run.state = "FAILED"
        system_blocked = client.get("/api/close", params={"run_id": client.run_id}).json()
        assert system_blocked["system_error_blockers"] == 1
        assert system_blocked["total_close_blockers"] == 7
        assert system_blocked["unresolved_paise"] == unresolved
    finally:
        client.__exit__(None, None, None)


def test_reviews_are_frozen_after_final_pack(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_approvable(client)
        approved = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Freeze reviews"})
        assert approved.status_code == 200
        exception = client.get("/api/exceptions", params={"run_id": client.run_id}).json()["items"][0]
        response = client.post(
            f"/api/exceptions/{exception['exception_id']}/review",
            json={"action": "APPROVE", "reason": "Late review"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "REVIEW_FROZEN"
        with client.app.state.database.session() as session:
            row = session.scalar(select(ExceptionRecord).where(ExceptionRecord.id == exception["exception_id"]))
            assert row.state == exception["state"]
    finally:
        client.__exit__(None, None, None)


def test_approval_replay_preserves_all_authoritative_metadata_and_bytes(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_approvable(client)
        first = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Original approval"})
        assert first.status_code == 200
        first_body = first.json()
        first_bytes = client.get("/api/close/export", params={"run_id": client.run_id}).content
        first_payload = json.loads(first_bytes)
        with client.app.state.database.session() as session:
            approval = session.scalar(select(CloseApprovalRecord).where(CloseApprovalRecord.run_id == client.run_id))
            original_time = approval.created_at
        replay = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Conflicting operator text"})
        assert replay.status_code == 200
        replay_body = replay.json()
        second_bytes = client.get("/api/close/export", params={"run_id": client.run_id}).content
        assert replay_body["idempotent_replay"] is True
        for field in ("approval_id", "actor_id", "reason", "state", "approved_at"):
            assert replay_body[field] == first_body[field]
        assert json.loads(second_bytes)["pack_fingerprint"] == first_payload["pack_fingerprint"]
        assert second_bytes == first_bytes
        with client.app.state.database.session() as session:
            approval = session.scalar(select(CloseApprovalRecord).where(CloseApprovalRecord.run_id == client.run_id))
            assert approval.created_at == original_time
            assert approval.actor_id == first_body["actor_id"]
            assert approval.reason == first_body["reason"]
    finally:
        client.__exit__(None, None, None)


def test_approval_timestamp_mutation_blocks_state_replay_and_export(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_approvable(client)
        first = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Original approval"})
        assert first.status_code == 200
        original = first.json()
        original_bytes = client.get("/api/close/export", params={"run_id": client.run_id}).content

        with client.app.state.database.session() as session:
            approval = session.scalar(select(CloseApprovalRecord).where(CloseApprovalRecord.run_id == client.run_id))
            assert approval is not None
            approval.created_at = approval.created_at.replace(year=approval.created_at.year + 1)

        state = client.get("/api/close", params={"run_id": client.run_id})
        assert state.status_code == 200
        state_body = state.json()
        assert state_body["state"] == "BLOCKED"
        assert state_body["integrity_blockers"] == 1
        assert state_body["total_close_blockers"] >= 1

        with pytest.raises(ClosePackIntegrityError):
            client.app.state.close_service.export_pack("demo_merchant", client.run_id)

        replay = client.post(
            "/api/close/approve",
            json={"run_id": client.run_id, "reason": "Conflicting operator text"},
        )
        assert replay.status_code == 409
        assert replay.json()["detail"] == {"code": "CLOSE_PACK_INTEGRITY_FAILURE"}

        exported = client.get("/api/close/export", params={"run_id": client.run_id})
        assert exported.status_code == 409
        assert exported.json()["detail"] == {"code": "CLOSE_PACK_INTEGRITY_FAILURE"}
        assert exported.content != original_bytes
        assert replay.json().get("approved_at") is None
        assert original["approved_at"] != _approval_created_at(client)

        audit = client.get("/api/audit", params={"run_id": client.run_id})
        assert audit.status_code == 200
        assert audit.json()["items"][-1]["object_type"] == "CLOSE_PACK_INTEGRITY"
    finally:
        client.__exit__(None, None, None)


def _approval_created_at(client: TestClient) -> str:
    """Read the durable value only to prove it differs from the original response."""
    with client.app.state.database.session() as session:
        approval = session.scalar(select(CloseApprovalRecord).where(CloseApprovalRecord.run_id == client.run_id))
        assert approval is not None
        value = approval.created_at
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_final_pack_contains_complete_authoritative_manifest(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_reviewed_approvable(client)
        approved = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Complete manifest"}).json()
        payload = json.loads(client.get("/api/close/export", params={"run_id": client.run_id}).content)
        assert payload["schema_version"] == "proofclose-close-pack/v2"
        assert payload["pack_state"] == "FINAL" and payload["immutable"] is True and payload["mutable"] is False
        assert set(payload["totals"]) == {"records_processed", "expected_paise", "explained_paise", "unresolved_paise"}
        assert {"settlement_exception_count", "review_item_count", "total_close_blockers"} <= payload.keys()
        assert {"id", "hash", "source_deliveries"} <= payload["source_snapshot"].keys()
        assert all({"source_id", "content_hash"} <= delivery.keys() for delivery in payload["source_snapshot"]["source_deliveries"])
        assert payload["proofs"]
        assert all(
            {"proof_id", "subject", "status", "decision_fingerprint", "artifact_fingerprint", "rule", "configuration", "source_rows"}
            <= proof.keys()
            for proof in payload["proofs"]
        )
        assert all({"exception_id", "proof_id", "exception_type", "amount_paise", "state"} <= item.keys() for item in payload["review_items"])
        assert all({"audit_id", "actor_id", "item_id", "reason", "created_at"} <= item.keys() for item in payload["audit"])
        assert payload["approval"]["approval_id"] == approved["approval_id"]
        assert {"actor_id", "reason", "created_at", "state"} <= payload["approval"].keys()
        assert payload["rule"] == {"name": "settlement_match", "version": "2.0", "settlement_version": "2.0"}
        assert payload["configuration"]["version"] == "2.0"
        assert payload["configuration"]["values"] == {
            "pending_hours": 3,
            "bank_match_window_hours": 48,
            "early_bank_tolerance_hours": 2,
            "future_clock_skew_minutes": 5,
        }
        assert payload["pack_fingerprint"].startswith("sha256:")
    finally:
        client.__exit__(None, None, None)


def test_api_tenant_scope_rejects_state_review_approval_and_export(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        exception = client.get("/api/exceptions", params={"run_id": client.run_id}).json()["items"][0]
        headers = {"X-Tenant-ID": "other_tenant", "X-Actor-ID": "demo_operator"}
        assert client.get("/api/close", params={"run_id": client.run_id}, headers=headers).status_code == 403
        assert client.post(
            f"/api/exceptions/{exception['exception_id']}/review",
            json={"action": "APPROVE", "reason": "Cross tenant"},
            headers=headers,
        ).status_code == 403
        assert client.post(
            "/api/close/approve", json={"run_id": client.run_id, "reason": "Cross tenant"}, headers=headers
        ).status_code == 403
        assert client.get("/api/close/export", params={"run_id": client.run_id}, headers=headers).status_code == 403
        with pytest.raises(KeyError):
            client.app.state.close_service.get_state("other_tenant", client.run_id)
        with pytest.raises(KeyError):
            client.app.state.close_service.approve("other_tenant", client.run_id, "other_operator", "Cross tenant")
        with pytest.raises(KeyError):
            client.app.state.close_service.export_pack("other_tenant", client.run_id)
        assert client.app.state.review_service.list_exceptions("other_tenant", client.run_id) == []
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("mutation", ["embedded_fingerprint", "storage_hash"])
def test_final_pack_authentication_mutations_never_return_corrupted_bytes(tmp_path, mutation: str) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_approvable(client)
        assert client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Mutation guard"}).status_code == 200
        with client.app.state.database.session() as session:
            pack = session.scalar(select(ClosePackRecord).where(ClosePackRecord.run_id == client.run_id))
            if mutation == "embedded_fingerprint":
                payload = json.loads(pack.payload_json)
                payload["pack_fingerprint"] = "sha256:tampered"
                pack.payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            else:
                pack.storage_hash = "sha256:tampered"
        response = client.get("/api/close/export", params={"run_id": client.run_id})
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": "CLOSE_PACK_INTEGRITY_FAILURE"}}
        state = client.get("/api/close", params={"run_id": client.run_id}).json()
        assert state["integrity_blockers"] == 1
        assert b"tampered" not in response.content
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("mutation", ["tenant_id", "run_id", "approval_id"])
def test_final_pack_identity_metadata_mutations_are_integrity_blockers(tmp_path, mutation: str) -> None:
    client = initialized_client(tmp_path)
    try:
        _make_approvable(client)
        assert client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Identity guard"}).status_code == 200
        with client.app.state.database.session() as session:
            pack = session.scalar(select(ClosePackRecord).where(ClosePackRecord.run_id == client.run_id))
            if mutation == "tenant_id":
                pack.tenant_id = "other_tenant"
            elif mutation == "run_id":
                original_run = session.scalar(select(RunRecord).where(RunRecord.id == client.run_id))
                session.add(
                    RunRecord(
                        id="moved_run",
                        tenant_id="demo_merchant",
                        source_snapshot_id=original_run.source_snapshot_id,
                        state=original_run.state,
                        rule_version=original_run.rule_version,
                        configuration_version=original_run.configuration_version,
                        records_processed=original_run.records_processed,
                        expected_paise=original_run.expected_paise,
                        explained_paise=original_run.explained_paise,
                        unresolved_paise=original_run.unresolved_paise,
                        total_ms=original_run.total_ms,
                        timings_json=original_run.timings_json,
                    )
                )
                session.flush()
                pack.run_id = "moved_run"
            else:
                session.add(
                    CloseApprovalRecord(
                        id="approval_moved",
                        tenant_id="other_tenant",
                        run_id=client.run_id,
                        actor_id="other_operator",
                        state="APPROVED_CLEAN",
                        reason="Other approval",
                    )
                )
                pack.approval_id = "approval_moved"
        response = client.get("/api/close/export", params={"run_id": client.run_id})
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": "CLOSE_PACK_INTEGRITY_FAILURE"}}
        assert response.content == b'{"detail":{"code":"CLOSE_PACK_INTEGRITY_FAILURE"}}'
        state = client.get("/api/close", params={"run_id": client.run_id}).json()
        assert state["integrity_blockers"] == 1
        replay = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Replay identity"})
        assert replay.status_code == 409
        assert replay.json() == {"detail": {"code": "CLOSE_PACK_INTEGRITY_FAILURE"}}
    finally:
        client.__exit__(None, None, None)


def test_tampered_proof_is_not_exportable_or_approvable(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        with client.app.state.database.session() as session:
            proof = session.scalar(select(ProofRecord).where(ProofRecord.run_id == client.run_id))
            payload = json.loads(proof.payload_json)
            payload["status"] = "tampered"
            proof.payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        state = client.get("/api/close", params={"run_id": client.run_id}).json()
        assert state["integrity_blockers"] == 1
        assert state["total_close_blockers"] >= 1
        assert client.get("/api/close/export", params={"run_id": client.run_id}).status_code == 409
        response = client.post("/api/close/approve", json={"run_id": client.run_id, "reason": "Tamper guard"})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CLOSE_POLICY_BLOCKED"
    finally:
        client.__exit__(None, None, None)
