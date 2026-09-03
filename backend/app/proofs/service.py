from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel

from app.domain.models import DecisionMaterial, ProofObject
from app.proofs.fingerprint import (
    ProofIntegrityError,
    artifact_fingerprint,
    decision_fingerprint,
    fingerprint_material,
    verify_artifact_fingerprint,
)
from app.proofs.legacy import LegacyProofObject, LegacyProofSchemaUnavailable
from app.proofs.registry import RuleRegistry, invoke_evaluator
from app.reconciliation.configuration import ConfigurationRegistry
from app.reconciliation.rules import EvaluationContext
from app.storage.repositories import ProofRecordIdentity


ProofMaterial = DecisionMaterial


class ProofOperationResult(BaseModel):
    status: Literal["REPRODUCED", "REEVALUATED", "FAILED"]
    failure_type: str | None = None
    original_fingerprint: str | None = None
    reproduced_fingerprint: str | None = None
    proof: ProofObject | None = None


class ProofArtifactStore(Protocol):
    def get(self, tenant_id: str, proof_id: str) -> ProofObject | LegacyProofObject | None: ...

    def get_identity(self, tenant_id: str, proof_id: str) -> ProofRecordIdentity | None: ...

    def list_for_run(self, tenant_id: str, run_id: str) -> list[ProofObject | LegacyProofObject]: ...

    def save(self, proof: ProofObject) -> None: ...

    def record_operation(self, proof: ProofObject, operation: str, result: ProofOperationResult) -> None: ...


class ProofService:
    def __init__(
        self,
        registry: RuleRegistry,
        now: Callable[[], datetime] | None = None,
        configurations: ConfigurationRegistry | None = None,
        store: ProofArtifactStore | None = None,
    ) -> None:
        self.registry = registry
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.configurations = configurations
        self.store = store
        self._proofs: dict[str, ProofObject | LegacyProofObject] = {}
        self.events: list[dict[str, Any]] = []

    def create(
        self,
        tenant_id: str,
        run_id: str,
        snapshot_id: str,
        rule_name: str,
        rule_version: str,
        configuration_version: str,
        material: DecisionMaterial,
        supersedes_proof_id: str | None = None,
    ) -> ProofObject:
        if (rule_name, rule_version, configuration_version) != (
            material.rule_name,
            material.rule_version,
            material.configuration.version,
        ):
            raise ValueError("proof identity must match its decision material")
        provisional = ProofObject(
            schema_version="proof-object/v2",
            proof_id=f"proof_{uuid4().hex[:16]}",
            tenant_id=tenant_id,
            run_id=run_id,
            source_snapshot_id=snapshot_id,
            **material.model_dump(mode="python"),
            decision_fingerprint=decision_fingerprint(material),
            supersedes_proof_id=supersedes_proof_id,
            created_at=self._now(),
            artifact_fingerprint="",
        )
        proof = provisional.model_copy(
            update={"artifact_fingerprint": artifact_fingerprint(provisional.model_dump(mode="python"))}
        )
        self._proofs[proof.proof_id] = proof
        return proof

    def get(self, proof_id: str, tenant_id: str | None = None) -> ProofObject | LegacyProofObject:
        proof = self._proofs.get(proof_id)
        # A durable store is authoritative whenever a tenant is supplied. This
        # prevents a cached proof from hiding a direct database tamper.
        if tenant_id is not None and self.store is not None:
            try:
                stored = self.store.get(tenant_id, proof_id)
            except (ProofIntegrityError, LegacyProofSchemaUnavailable):
                self._proofs.pop(proof_id, None)
                raise
            if stored is not None:
                proof = stored
                self._proofs[proof.proof_id] = proof
            else:
                self._proofs.pop(proof_id, None)
                proof = None
        if proof is None or (tenant_id is not None and proof.tenant_id != tenant_id):
            raise KeyError(proof_id)
        if isinstance(proof, ProofObject):
            try:
                verify_artifact_fingerprint(proof.model_dump(mode="python"))
            except ProofIntegrityError:
                raise
        else:
            # v1 has no artifact fingerprint. Preserve its original decision
            # fingerprint semantics instead of inventing a v2 integrity claim.
            proof.verify_original_decision_fingerprint()
        return proof

    def list_for_run(self, tenant_id: str, run_id: str) -> list[ProofObject | LegacyProofObject]:
        if self.store is not None:
            durable_list = getattr(self.store, "list_for_run", None)
            if not callable(durable_list):
                return []
            proofs = durable_list(tenant_id, run_id)
            for proof in proofs:
                if proof.tenant_id != tenant_id or proof.run_id != run_id:
                    raise KeyError(proof.proof_id)
                if isinstance(proof, ProofObject):
                    verify_artifact_fingerprint(proof.model_dump(mode="python"))
                else:
                    proof.verify_original_decision_fingerprint()
                self._proofs[proof.proof_id] = proof
            return proofs
        proofs = [proof for proof in self._proofs.values() if proof.tenant_id == tenant_id and proof.run_id == run_id]
        for proof in proofs:
            if isinstance(proof, ProofObject):
                verify_artifact_fingerprint(proof.model_dump(mode="python"))
            else:
                proof.verify_original_decision_fingerprint()
        return proofs

    def clear(self) -> None:
        self._proofs.clear()
        self.events.clear()

    def discard_run_cache(self, run_id: str) -> None:
        self._proofs = {proof_id: proof for proof_id, proof in self._proofs.items() if proof.run_id != run_id}

    def _record_operation(self, proof: ProofObject | LegacyProofObject, operation: str, result: ProofOperationResult) -> None:
        self.events.append({"proof_id": proof.proof_id, "operation": operation, **result.model_dump(mode="json")})
        if self.store is not None:
            self.store.record_operation(proof, operation, result)

    def _record_integrity_failure(self, proof_id: str, tenant_id: str | None, operation: str) -> None:
        """Record tamper only with trusted tenant-scoped row identity, if available."""
        if tenant_id is None or self.store is None:
            return
        get_identity = getattr(self.store, "get_identity", None)
        if not callable(get_identity):
            return
        identity = get_identity(tenant_id, proof_id)
        if not isinstance(identity, ProofRecordIdentity):
            return
        result = ProofOperationResult(status="FAILED", failure_type="PROOF_ARTIFACT_TAMPERED")
        self._record_operation(identity, operation, result)  # type: ignore[arg-type]

    def reproduce(self, proof_id: str, tenant_id: str | None = None) -> ProofOperationResult:
        try:
            proof = self.get(proof_id, tenant_id)
        except ProofIntegrityError:
            self._record_integrity_failure(proof_id, tenant_id, "HISTORICAL_REPRODUCTION")
            return ProofOperationResult(status="FAILED", failure_type="PROOF_ARTIFACT_TAMPERED")
        except LegacyProofSchemaUnavailable:
            return ProofOperationResult(status="FAILED", failure_type="LEGACY_PROOF_SCHEMA_UNAVAILABLE")
        evaluator = self.registry.resolve(proof.rule_name, proof.rule_version)
        if evaluator is None:
            result = ProofOperationResult(
                status="FAILED",
                failure_type="RULE_IMPLEMENTATION_UNAVAILABLE",
                original_fingerprint=proof.proof_fingerprint,
            )
            self._record_operation(proof, "HISTORICAL_REPRODUCTION", result)
            return result
        if isinstance(proof, LegacyProofObject):
            try:
                self._validate_legacy_inputs(proof)
            except ValueError:
                result = ProofOperationResult(status="FAILED", failure_type="CONFIGURATION_PAYLOAD_INCOMPATIBLE")
                self._record_operation(proof, "HISTORICAL_REPRODUCTION", result)
                return result
            reproduced_material = invoke_evaluator(evaluator, dict(proof.inputs))
            reproduced_fingerprint = fingerprint_material(reproduced_material)
            original_fingerprint = proof.proof_fingerprint
        else:
            try:
                self._validate_configuration(proof.rule_name, proof.rule_version, proof.configuration)
            except ValueError:
                result = ProofOperationResult(status="FAILED", failure_type="CONFIGURATION_PAYLOAD_INCOMPATIBLE")
                self._record_operation(proof, "HISTORICAL_REPRODUCTION", result)
                return result
            reproduced_material = invoke_evaluator(
                evaluator,
                dict(proof.evidence_inputs),
                EvaluationContext(configuration=proof.configuration, evaluated_at=proof.evaluated_at),
            )
            reproduced_fingerprint = decision_fingerprint(reproduced_material)
            original_fingerprint = proof.decision_fingerprint
        if reproduced_fingerprint != original_fingerprint:
            result = ProofOperationResult(
                status="FAILED",
                failure_type="PROOF_REPRODUCIBILITY_FAILURE",
                original_fingerprint=original_fingerprint,
                reproduced_fingerprint=reproduced_fingerprint,
            )
        else:
            result = ProofOperationResult(
                status="REPRODUCED",
                original_fingerprint=original_fingerprint,
                reproduced_fingerprint=reproduced_fingerprint,
            )
        self._record_operation(proof, "HISTORICAL_REPRODUCTION", result)
        return result

    def reevaluate(
        self,
        proof_id: str,
        tenant_id: str | None = None,
    ) -> ProofOperationResult:
        try:
            original = self.get(proof_id, tenant_id)
        except ProofIntegrityError:
            self._record_integrity_failure(proof_id, tenant_id, "CURRENT_RULE_REEVALUATION")
            return ProofOperationResult(status="FAILED", failure_type="PROOF_ARTIFACT_TAMPERED")
        except LegacyProofSchemaUnavailable:
            return ProofOperationResult(status="FAILED", failure_type="LEGACY_PROOF_SCHEMA_UNAVAILABLE")
        if isinstance(original, LegacyProofObject):
            result = ProofOperationResult(status="FAILED", failure_type="LEGACY_PROOF_SCHEMA_UNAVAILABLE")
            self._record_operation(original, "CURRENT_RULE_REEVALUATION", result)
            return result
        current = self.registry.current(original.rule_name)
        if current is None:
            result = ProofOperationResult(status="FAILED", failure_type="RULE_IMPLEMENTATION_UNAVAILABLE")
            self._record_operation(original, "CURRENT_RULE_REEVALUATION", result)
            return result
        version, evaluator = current
        configuration = self.configurations.current() if self.configurations is not None else None
        if configuration is None:
            result = ProofOperationResult(status="FAILED", failure_type="CONFIGURATION_PAYLOAD_INCOMPATIBLE")
            self._record_operation(original, "CURRENT_RULE_REEVALUATION", result)
            return result
        try:
            self._validate_configuration(original.rule_name, version, configuration)
        except ValueError:
            result = ProofOperationResult(status="FAILED", failure_type="CONFIGURATION_PAYLOAD_INCOMPATIBLE")
            self._record_operation(original, "CURRENT_RULE_REEVALUATION", result)
            return result
        context = EvaluationContext(configuration=configuration, evaluated_at=self._now())
        material = invoke_evaluator(evaluator, dict(original.evidence_inputs), context)
        if isinstance(material, DecisionMaterial):
            if tuple(material.source_rows) != tuple(original.source_rows) or material.evidence_inputs != original.evidence_inputs:
                result = ProofOperationResult(status="FAILED", failure_type="PROOF_REPRODUCIBILITY_FAILURE")
                self._record_operation(original, "CURRENT_RULE_REEVALUATION", result)
                return result
            # The operation clock, not evaluator-provided input, defines the
            # time of a current re-evaluation.
            material = material.model_copy(update={"evaluated_at": context.evaluated_at})
        proof = self.create(
            original.tenant_id,
            original.run_id,
            original.source_snapshot_id,
            original.rule_name,
            version,
            configuration.version,
            material,
            supersedes_proof_id=original.proof_id,
        )
        result = ProofOperationResult(status="REEVALUATED", proof=proof)
        if self.store is not None:
            self.store.save(proof)
        self._record_operation(original, "CURRENT_RULE_REEVALUATION", result)
        return result

    @staticmethod
    def _validate_configuration(rule_name: str, rule_version: str, configuration: Any) -> None:
        """Validate the exact configuration schema before invoking rule code."""
        values = configuration.values.as_dict()
        expected = {
            "pending_hours",
            "bank_match_window_hours",
            "early_bank_tolerance_hours",
            "future_clock_skew_minutes",
        }
        if rule_name == "settlement_match" and rule_version == "1.0":
            expected = {"pending_hours", "amount_candidate_window_hours"}
        if set(values) != expected or any(
            isinstance(value, bool) or not isinstance(value, int) for value in values.values()
        ):
            raise ValueError("incompatible configuration payload")

    @staticmethod
    def _validate_legacy_inputs(proof: LegacyProofObject) -> None:
        inputs = proof.inputs
        # The earliest v1 proofs did not persist the policy at all. Historical
        # reproduction must use those original inputs exactly, without
        # inventing configuration that was never recorded. Later v1 payloads
        # may include policy, but a present policy is still validated strictly.
        if "policy" not in inputs:
            return
        policy = inputs["policy"]
        if not isinstance(policy, dict) or set(policy) != {"pending_hours", "amount_candidate_window_hours"}:
            raise ValueError("incompatible legacy configuration payload")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in policy.values()):
            raise ValueError("incompatible legacy configuration payload")
