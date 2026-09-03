from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from pydantic import ValidationError

from app.domain.enums import Classification, Decision, ExceptionType, SubjectType
from app.domain.models import ConfigurationBundle, DecisionMaterial, MatchEvidence, ProofObject, ProofResult, ProofSubject, SourceReference
from app.proofs.fingerprint import (
    ProofIntegrityError,
    artifact_fingerprint,
    decision_fingerprint,
    fingerprint_material,
    verify_artifact_fingerprint,
)
from app.proofs.legacy import LegacyProofObject, LegacyProofSchemaUnavailable, parse_stored_proof
from app.proofs.registry import RuleRegistry
from app.proofs.service import ProofService


def material(
    observed: int = 475_000,
    rule_version: str = "2.0",
    configuration_version: str = "2.0",
) -> DecisionMaterial:
    configuration_values = (
        {
            "pending_hours": 3,
            "bank_match_window_hours": 48,
            "early_bank_tolerance_hours": 2,
            "future_clock_skew_minutes": 5,
        }
        if configuration_version == "2.0"
        else {"pending_hours": 3, "amount_candidate_window_hours": 48}
    )
    return DecisionMaterial(
        subject=ProofSubject(subject_type=SubjectType.SETTLEMENT, subject_id="setl_1"),
        rule_name="settlement_match",
        rule_version=rule_version,
        configuration=ConfigurationBundle(version=configuration_version, values=configuration_values),
        status=Decision.AUTO_VERIFIED,
        source_rows=(SourceReference(table="bank_statement", id="bank_1", raw_hash="sha256:abc"),),
        evidence_inputs={"settlement": {"amount_paise": 475_000}, "observed_credit_paise": observed},
        evaluated_at=datetime(2026, 8, 26, 12, tzinfo=timezone.utc),
        formula="sum(credit_paise) - sum(debit_paise)",
        result=ProofResult(expected_paise=475_000, observed_paise=observed, delta_paise=observed - 475_000),
        evidence=MatchEvidence(
            utr_exact=True,
            amount_exact=observed == 475_000,
            settlement_ledger_consistent=True,
            temporal_consistency=True,
            candidate_count=1,
            amount_delta_paise=observed - 475_000,
        ),
        decision_score=100,
        decision_reasons=("UTR exact", "Unique bank candidate", "Amount exact"),
        classification=Classification.CALCULATED,
    )


def build_service() -> ProofService:
    return ProofService(RuleRegistry(), now=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc))


def base_proof_payload() -> dict:
    decision = material()
    payload = {
        "schema_version": "proof-object/v2",
        "proof_id": "proof_1",
        "tenant_id": "demo",
        "run_id": "run_1",
        "subject": decision.subject.model_dump(mode="json"),
        "source_snapshot_id": "snapshot_1",
        "status": decision.status.value,
        "source_rows": [row.model_dump(mode="json") for row in decision.source_rows],
        "rule_name": decision.rule_name,
        "rule_version": decision.rule_version,
        "configuration": decision.configuration.model_dump(mode="json"),
        "evidence_inputs": decision.evidence_inputs,
        "evaluated_at": "2026-08-26T12:00:00Z",
        "formula": decision.formula,
        "result": decision.result.model_dump(mode="json"),
        "evidence": decision.evidence.model_dump(mode="json"),
        "decision_score": decision.decision_score,
        "decision_reasons": list(decision.decision_reasons),
        "classification": decision.classification.value,
        "exception_type": None,
        "unresolved_reason": None,
        "decision_fingerprint": decision_fingerprint(decision),
        "supersedes_proof_id": None,
        "created_at": "2026-08-26T12:02:00Z",
    }
    payload["artifact_fingerprint"] = artifact_fingerprint(payload)
    return payload


def mutate_copy(value: dict, path: tuple[object, ...], replacement: object) -> dict:
    changed = deepcopy(value)
    target = changed
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement
    return changed


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("subject", "subject_type"), "ORDER"),
        (("subject", "subject_id"), "setl_changed"),
        (("rule_name",), "order_payment_consistency"),
        (("rule_version",), "9.9"),
        (("configuration", "version"), "9.9"),
        (("configuration", "values", "pending_hours"), 4),
        (("source_rows", 0, "table"), "settlements"),
        (("source_rows", 0, "id"), "bank_changed"),
        (("source_rows", 0, "raw_hash"), "sha256:changed"),
        (("evidence_inputs", "settlement", "amount_paise"), 101),
        (("evaluated_at",), "2026-08-26T12:01:00Z"),
        (("status",), "REFUSED"),
        (("formula",), "changed"),
        (("result", "expected_paise"), 101),
        (("evidence", "candidate_count"), 2),
        (("decision_score",), 99),
        (("decision_reasons",), ["changed"]),
        (("classification",), "inferred"),
        (("exception_type",), "AMBIGUOUS_MATCH"),
        (("unresolved_reason",), "changed"),
    ],
)
def test_every_decision_field_is_bound(path: tuple[object, ...], replacement: object) -> None:
    """Removing any canonical decision input would let that financial decision be silently rewritten."""
    original = base_proof_payload()
    changed = mutate_copy(original, path, replacement)

    assert decision_fingerprint(original) != decision_fingerprint(changed)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema_version",), "proof-object/v9"),
        (("proof_id",), "proof_changed"),
        (("tenant_id",), "other_tenant"),
        (("run_id",), "run_changed"),
        (("subject", "subject_id"), "setl_changed"),
        (("source_snapshot_id",), "snapshot_changed"),
        (("status",), "REFUSED"),
        (("source_rows", 0, "table"), "settlements"),
        (("source_rows", 0, "id"), "bank_changed"),
        (("source_rows", 0, "raw_hash"), "sha256:changed"),
        (("rule_name",), "changed"),
        (("rule_version",), "9.9"),
        (("configuration", "version"), "9.9"),
        (("configuration", "values", "pending_hours"), 4),
        (("evidence_inputs", "settlement", "amount_paise"), 101),
        (("evaluated_at",), "2026-08-26T12:01:00Z"),
        (("formula",), "changed"),
        (("result", "expected_paise"), 101),
        (("evidence", "candidate_count"), 2),
        (("decision_score",), 99),
        (("decision_reasons",), ["changed"]),
        (("classification",), "inferred"),
        (("exception_type",), "AMBIGUOUS_MATCH"),
        (("unresolved_reason",), "changed"),
        (("decision_fingerprint",), "sha256:changed"),
        (("supersedes_proof_id",), "proof_previous"),
        (("created_at",), "2026-08-26T12:03:00Z"),
    ],
)
def test_every_v2_artifact_field_is_bound(path: tuple[object, ...], replacement: object) -> None:
    """Changing any persisted v2 field must invalidate its artifact identity."""
    original = base_proof_payload()
    changed = mutate_copy(original, path, replacement)

    assert artifact_fingerprint(original) != artifact_fingerprint(changed)


def test_artifact_fingerprint_omits_only_its_stored_value_and_detects_tampering() -> None:
    """An attacker may replace the stored digest but cannot change its recomputed value."""
    payload = base_proof_payload()
    changed_digest = mutate_copy(payload, ("artifact_fingerprint",), "sha256:changed")

    assert artifact_fingerprint(payload) == artifact_fingerprint(changed_digest)
    verify_artifact_fingerprint(payload)
    with pytest.raises(ProofIntegrityError):
        verify_artifact_fingerprint(changed_digest)


def test_source_row_order_is_canonical_for_both_fingerprints() -> None:
    """Equivalent evidence row sets must not acquire different identities from input ordering."""
    payload = base_proof_payload()
    payload["source_rows"].append({"table": "settlements", "id": "setl_1", "raw_hash": "sha256:def"})
    reordered = deepcopy(payload)
    reordered["source_rows"].reverse()

    assert decision_fingerprint(payload) == decision_fingerprint(reordered)
    assert artifact_fingerprint(payload) == artifact_fingerprint(reordered)


def test_stored_v2_proof_is_verified_before_parsing() -> None:
    """A repository read must reject a tampered v2 payload before any caller can use it."""
    payload = base_proof_payload()

    parsed = parse_stored_proof(json.dumps(payload))
    assert parsed.proof_id == "proof_1"
    with pytest.raises(ProofIntegrityError):
        parse_stored_proof(json.dumps(mutate_copy(payload, ("tenant_id",), "other_tenant")))


def test_timestamp_strings_have_one_utc_z_fingerprint_representation() -> None:
    """Equivalent UTC spellings must not create different decision or artifact identities."""
    payload = base_proof_payload()
    equivalent = mutate_copy(payload, ("evaluated_at",), "2026-08-26T12:00:00+00:00")
    equivalent = mutate_copy(equivalent, ("created_at",), "2026-08-26T12:02:00+00:00")

    assert decision_fingerprint(payload) == decision_fingerprint(equivalent)
    assert artifact_fingerprint(payload) == artifact_fingerprint(equivalent)


def test_v2_load_rejects_noncanonical_timestamp_strings_after_hash_verification() -> None:
    """A v2 payload must store canonical UTC-Z timestamps, even when an offset spelling is equivalent."""
    payload = mutate_copy(base_proof_payload(), ("evaluated_at",), "2026-08-26T12:00:00+00:00")
    payload["artifact_fingerprint"] = artifact_fingerprint(payload)

    with pytest.raises(ValidationError, match="UTC-Z"):
        parse_stored_proof(json.dumps(payload))


def test_v2_load_rejects_space_separated_utc_timestamp_strings() -> None:
    """A trailing Z alone is insufficient: stored v2 timestamps must use canonical ISO T notation."""
    payload = mutate_copy(base_proof_payload(), ("created_at",), "2026-08-26 12:02:00Z")
    payload["artifact_fingerprint"] = artifact_fingerprint(payload)

    with pytest.raises(ValidationError, match="UTC-Z"):
        parse_stored_proof(json.dumps(payload))


def test_timestamp_looking_non_timestamp_evidence_strings_remain_bound_verbatim() -> None:
    """Formulae, reasons, and evidence notes are text, not timestamps eligible for canonical rewriting."""
    payload = base_proof_payload()
    payload["formula"] = "2026-08-26T12:00:00Z"
    payload["decision_reasons"] = ["2026-08-26T12:00:00Z"]
    payload["evidence_inputs"]["note"] = "2026-08-26T12:00:00Z"
    changed = deepcopy(payload)
    changed["formula"] = "2026-08-26T12:00:00+00:00"
    changed["decision_reasons"] = ["2026-08-26T12:00:00+00:00"]
    changed["evidence_inputs"]["note"] = "2026-08-26T12:00:00+00:00"

    assert decision_fingerprint(payload) != decision_fingerprint(changed)
    assert artifact_fingerprint(payload) != artifact_fingerprint(changed)


def test_explicit_evidence_timestamp_keys_have_one_utc_z_fingerprint_representation() -> None:
    """Typed source timestamp keys retain semantic UTC equivalence inside evidence inputs."""
    payload = base_proof_payload()
    payload["evidence_inputs"]["settlement"]["created_at"] = "2026-08-26T12:00:00Z"
    equivalent = deepcopy(payload)
    equivalent["evidence_inputs"]["settlement"]["created_at"] = "2026-08-26T12:00:00+00:00"

    assert decision_fingerprint(payload) == decision_fingerprint(equivalent)
    assert artifact_fingerprint(payload) == artifact_fingerprint(equivalent)


@pytest.mark.parametrize(
    ("path",),
    [
        (("evaluated_at",),),
        (("evidence_inputs", "settlement", "created_at"),),
    ],
)
def test_naive_datetimes_in_canonical_timestamp_fields_are_rejected(path: tuple[object, ...]) -> None:
    """A naive time has no auditable UTC meaning and must never enter a proof fingerprint."""
    payload = base_proof_payload()
    changed = mutate_copy(payload, path, datetime(2026, 8, 26, 12))

    with pytest.raises(ValueError, match="timezone-aware"):
        decision_fingerprint(changed)


def test_legacy_proof_is_lossless_and_invalid_legacy_is_explicit() -> None:
    """Legacy audit data must remain readable without guessing the v2 fields it never recorded."""
    payload = {
        "proof_id": "proof_legacy",
        "tenant_id": "demo",
        "run_id": "run_1",
        "source_snapshot_id": "snapshot_1",
        "status": "AUTO_VERIFIED",
        "source_rows": [{"table": "bank_statement", "id": "bank_1", "raw_hash": "sha256:abc"}],
        "rule_name": "settlement_match",
        "rule_version": "1.0",
        "configuration_version": "1.0",
        "inputs": {"observed_credit_paise": 475_000},
        "formula": "observed",
        "result": {"expected_paise": 475_000, "observed_paise": 475_000, "delta_paise": 0},
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
        "proof_fingerprint": "",
        "supersedes_proof_id": None,
        "created_at": "2026-08-26T12:00:00Z",
    }
    payload["proof_fingerprint"] = fingerprint_material(
        {
            key: payload[key]
            for key in (
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
            )
        }
    )

    parsed = parse_stored_proof(json.dumps(payload))
    assert isinstance(parsed, LegacyProofObject)
    assert parsed.proof_fingerprint == payload["proof_fingerprint"]
    assert parsed.inputs == {"observed_credit_paise": 475_000}
    with pytest.raises(LegacyProofSchemaUnavailable, match="LEGACY_PROOF_SCHEMA_UNAVAILABLE"):
        parse_stored_proof(json.dumps({"proof_id": "incomplete"}))


def test_historical_reproduction_fails_when_rule_implementation_is_unavailable() -> None:
    """Falling back to current code would falsely claim historical reproducibility."""
    service = build_service()
    proof = service.create(
        tenant_id="demo",
        run_id="run_1",
        snapshot_id="snapshot_1",
        rule_name="settlement_match",
        rule_version="1.0",
        configuration_version="1.0",
        material=material(rule_version="1.0", configuration_version="1.0"),
    )
    result = service.reproduce(proof.proof_id)
    assert result.status == "FAILED"
    assert result.failure_type == "RULE_IMPLEMENTATION_UNAVAILABLE"


def test_historical_reproduction_dispatches_exact_version() -> None:
    """Registering only the exact original rule must reproduce the stored fingerprint."""
    service = build_service()
    service.registry.register("settlement_match", "1.0", lambda inputs: material(inputs["observed_credit_paise"], "1.0", "1.0"))
    proof = service.create(
        "demo", "run_1", "snapshot_1", "settlement_match", "1.0", "1.0", material(rule_version="1.0", configuration_version="1.0")
    )
    result = service.reproduce(proof.proof_id)
    assert result.status == "REPRODUCED"
    assert result.original_fingerprint == result.reproduced_fingerprint


def test_current_rule_reevaluation_creates_linked_proof() -> None:
    """Re-evaluation must preserve the old artifact and create a linked new one."""
    from app.reconciliation.configuration import CONFIGURATION_BUNDLE_V2, ConfigurationRegistry

    configurations = ConfigurationRegistry()
    configurations.register(CONFIGURATION_BUNDLE_V2)
    configurations.set_current("2.0")
    service = ProofService(RuleRegistry(), now=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc), configurations=configurations)
    service.registry.register("settlement_match", "2.0", lambda inputs: material(inputs["observed_credit_paise"], "2.0", "2.0"))
    service.registry.set_current("settlement_match", "2.0")
    old = service.create(
        "demo", "run_1", "snapshot_1", "settlement_match", "1.0", "1.0", material(rule_version="1.0", configuration_version="1.0")
    )
    result = service.reevaluate(old.proof_id)
    assert result.status == "REEVALUATED"
    assert result.proof is not None
    assert result.proof.proof_id != old.proof_id
    assert result.proof.supersedes_proof_id == old.proof_id
    assert result.proof.rule_version == "2.0"


def test_v2_historical_reproduction_supports_retained_one_argument_evaluator() -> None:
    """A retained v2 evaluator may keep the original one-input callable contract."""
    service = build_service()
    service.registry.register(
        "settlement_match",
        "2.0",
        lambda inputs: material(inputs["observed_credit_paise"], "2.0", "2.0"),
    )
    proof = service.create(
        "demo",
        "run_1",
        "snapshot_1",
        "settlement_match",
        "2.0",
        "2.0",
        material(rule_version="2.0", configuration_version="2.0"),
    )

    result = service.reproduce(proof.proof_id)

    assert result.status == "REPRODUCED"
    assert result.original_fingerprint == result.reproduced_fingerprint


def test_v2_evaluator_type_error_is_not_retried_with_a_different_signature() -> None:
    """A TypeError raised by evaluator logic must surface, not trigger an unsafe fallback call."""
    service = build_service()
    calls: list[int] = []

    def evaluator(inputs: dict, context: object) -> DecisionMaterial:
        calls.append(1)
        raise TypeError("evaluator body failed")

    service.registry.register("settlement_match", "2.0", evaluator)
    proof = service.create(
        "demo",
        "run_1",
        "snapshot_1",
        "settlement_match",
        "2.0",
        "2.0",
        material(rule_version="2.0", configuration_version="2.0"),
    )

    with pytest.raises(TypeError, match="evaluator body failed"):
        service.reproduce(proof.proof_id)

    assert len(calls) == 1


def test_current_reevaluation_uses_registered_configuration_and_service_clock() -> None:
    from app.reconciliation.configuration import CONFIGURATION_BUNDLE_V2, ConfigurationRegistry

    configurations = ConfigurationRegistry()
    configurations.register(CONFIGURATION_BUNDLE_V2)
    configurations.set_current("2.0")
    clock_time = datetime(2026, 8, 27, 15, 30, tzinfo=timezone.utc)
    service = ProofService(RuleRegistry(), now=lambda: clock_time, configurations=configurations)
    calls: list[object] = []

    def evaluator(inputs: dict, context: object) -> DecisionMaterial:
        calls.append(context)
        return material(inputs["observed_credit_paise"], "2.0", "2.0")

    service.registry.register("settlement_match", "2.0", evaluator)
    service.registry.set_current("settlement_match", "2.0")
    original = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())
    before = original.model_dump(mode="json")

    result = service.reevaluate(original.proof_id, "demo")

    assert result.status == "REEVALUATED"
    assert result.proof is not None
    assert result.proof.configuration.model_dump(mode="json") == CONFIGURATION_BUNDLE_V2.model_dump(mode="json")
    assert result.proof.evaluated_at == clock_time
    assert result.proof.supersedes_proof_id == original.proof_id
    assert original.model_dump(mode="json") == before
    assert calls


def test_current_reevaluation_does_not_accept_caller_configuration_selection() -> None:
    service = build_service()
    with pytest.raises(TypeError):
        service.reevaluate("proof_1", tenant_id="demo", configuration_version="1.0")


def test_incompatible_historical_configuration_fails_before_evaluator() -> None:
    service = build_service()
    calls: list[int] = []

    def evaluator(inputs: dict, context: object) -> DecisionMaterial:
        calls.append(1)
        return material(inputs["observed_credit_paise"])

    service.registry.register("settlement_match", "2.0", evaluator)
    original = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())
    changed = original.model_copy(
        update={"configuration": ConfigurationBundle(version="2.0", values={"pending_hours": "bad"})}
    )
    changed = changed.model_copy(update={"artifact_fingerprint": artifact_fingerprint(changed.model_dump(mode="python"))})
    service._proofs[original.proof_id] = changed

    result = service.reproduce(original.proof_id, "demo")

    assert result.failure_type == "CONFIGURATION_PAYLOAD_INCOMPATIBLE"
    assert calls == []


def test_v2_tamper_fails_before_evaluator() -> None:
    service = build_service()
    calls: list[int] = []

    def evaluator(inputs: dict, context: object) -> DecisionMaterial:
        calls.append(1)
        return material(inputs["observed_credit_paise"])

    service.registry.register("settlement_match", "2.0", evaluator)
    original = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())
    service._proofs[original.proof_id] = original.model_copy(update={"decision_score": 1})

    result = service.reproduce(original.proof_id, "demo")

    assert result.failure_type == "PROOF_ARTIFACT_TAMPERED"
    assert calls == []


def test_v2_supersession_tamper_fails_before_evaluator() -> None:
    service = build_service()
    calls: list[int] = []

    def evaluator(inputs: dict, context: object) -> DecisionMaterial:
        calls.append(1)
        return material(inputs["observed_credit_paise"])

    service.registry.register("settlement_match", "2.0", evaluator)
    original = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())
    service._proofs[original.proof_id] = original.model_copy(update={"supersedes_proof_id": "proof_prior"})

    result = service.reproduce(original.proof_id, "demo")

    assert result.failure_type == "PROOF_ARTIFACT_TAMPERED"
    assert calls == []


def test_historical_decision_mismatch_is_explicit() -> None:
    service = build_service()

    service.registry.register("settlement_match", "2.0", lambda inputs: material(474_999))
    original = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())

    result = service.reproduce(original.proof_id, "demo")

    assert result.failure_type == "PROOF_REPRODUCIBILITY_FAILURE"
    assert result.original_fingerprint != result.reproduced_fingerprint


class _DurableProofStore:
    def __init__(self, proofs: list[ProofObject] | None = None) -> None:
        self.proofs = {proof.proof_id: proof for proof in (proofs or [])}
        self.operations: list[tuple[object, str, object]] = []

    def get(self, tenant_id: str, proof_id: str):
        proof = self.proofs.get(proof_id)
        return proof if proof is not None and proof.tenant_id == tenant_id else None

    def list_for_run(self, tenant_id: str, run_id: str):
        return [
            proof
            for proof in self.proofs.values()
            if proof.tenant_id == tenant_id and proof.run_id == run_id
        ]

    def get_identity(self, tenant_id: str, proof_id: str):
        proof = self.proofs.get(proof_id)
        if proof is None or proof.tenant_id != tenant_id:
            return None
        return proof

    def save(self, proof: ProofObject) -> None:
        self.proofs[proof.proof_id] = proof

    def record_operation(self, proof, operation: str, result: object) -> None:
        self.operations.append((proof, operation, result))


def test_tenant_scoped_missing_durable_proof_evicts_stale_cache() -> None:
    service = build_service()
    proof = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())
    service.store = _DurableProofStore()

    with pytest.raises(KeyError):
        service.get(proof.proof_id, tenant_id="demo")

    assert proof.proof_id not in service._proofs


def test_list_for_run_reads_durable_tenant_records_and_verifies_each() -> None:
    service = build_service()
    proof = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())
    service.store = _DurableProofStore([proof])
    service._proofs.clear()

    assert service.list_for_run("demo", "run_1") == [proof]

    service.store.proofs[proof.proof_id] = proof.model_copy(update={"decision_score": 1})
    with pytest.raises(ProofIntegrityError):
        service.list_for_run("demo", "run_1")


def test_current_reevaluation_rejects_evaluator_provenance_mutation() -> None:
    from app.reconciliation.configuration import CONFIGURATION_BUNDLE_V2, ConfigurationRegistry

    configurations = ConfigurationRegistry()
    configurations.register(CONFIGURATION_BUNDLE_V2)
    configurations.set_current("2.0")
    service = ProofService(RuleRegistry(), configurations=configurations)
    original = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())

    def evaluator(inputs: dict, context: object) -> DecisionMaterial:
        changed = material(inputs["observed_credit_paise"])
        return changed.model_copy(
            update={
                "source_rows": (SourceReference(table="bank_statement", id="other", raw_hash="sha256:x"),),
                "evidence_inputs": {"observed_credit_paise": 1},
            }
        )

    service.registry.register("settlement_match", "2.0", evaluator)
    service.registry.set_current("settlement_match", "2.0")

    result = service.reevaluate(original.proof_id, tenant_id="demo")

    assert result.status == "FAILED"
    assert result.failure_type == "PROOF_REPRODUCIBILITY_FAILURE"
    assert result.proof is None
    assert service.get(original.proof_id, tenant_id="demo") == original


def test_current_rule_stale_pointer_is_unavailable_without_key_error() -> None:
    registry = RuleRegistry()
    registry.register("settlement_match", "2.0", lambda inputs: inputs)
    registry.set_current("settlement_match", "2.0")
    registry.remove("settlement_match", "2.0")

    assert registry.current("settlement_match") is None


def test_current_reevaluation_uses_stable_rule_unavailable_failure() -> None:
    from app.reconciliation.configuration import CONFIGURATION_BUNDLE_V2, ConfigurationRegistry

    configurations = ConfigurationRegistry()
    configurations.register(CONFIGURATION_BUNDLE_V2)
    configurations.set_current("2.0")
    registry = RuleRegistry()
    registry.register("settlement_match", "2.0", lambda inputs: material())
    registry.set_current("settlement_match", "2.0")
    registry.remove("settlement_match", "2.0")
    service = ProofService(registry, configurations=configurations)
    original = service.create("demo", "run_1", "snapshot_1", "settlement_match", "2.0", "2.0", material())

    result = service.reevaluate(original.proof_id, tenant_id="demo")

    assert result.status == "FAILED"
    assert result.failure_type == "RULE_IMPLEMENTATION_UNAVAILABLE"
