from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from time import perf_counter
from uuid import uuid4

from sqlalchemy import select

from app.domain.enums import Classification, Decision, SubjectType
from app.domain.models import (
    BankLine,
    ConfigurationBundle,
    DecisionMaterial,
    MatchEvidence,
    MerchantOrder,
    OrderEvidence,
    ProofObject,
    ProofResult,
    ProofSubject,
    ReconRow,
    Settlement,
    SourceReference,
)
from app.observability.store import ObservabilityStore
from app.observability.timing import measured
from app.proofs.service import ProofService
from app.reconciliation.allocation import allocate_settlements
from app.reconciliation.configuration import ConfigurationRegistry
from app.reconciliation.engine import (
    ReconciliationDecision,
    SettlementLedger,
    detect_order_exception,
    match_settlement,
    match_settlement_v1,
    reconstruct_settlement,
)
from app.reconciliation.rules import (
    EvaluationContext,
    ORDER_RULE_NAME,
    ORDER_RULE_VERSION_V1,
    OrderDecision,
    ReconciliationPolicy,
    ReconciliationPolicyV2,
    SETTLEMENT_RULE_NAME,
    SETTLEMENT_RULE_VERSION_V1,
    SETTLEMENT_RULE_VERSION_V2,
)
from app.storage.database import DatabaseManager
from app.storage.repositories import SnapshotRepository, SourceRepository
from app.storage.schema import ExceptionRecord, ProofRecord, ReconciliationRecord, RunRecord


NON_PROCESSABLE_STATUSES = frozenset({"failed", "cancelled", "reversed"})


@dataclass(frozen=True)
class PreparedSettlementResult:
    settlement: Settlement
    decision: ReconciliationDecision
    proof: ProofObject
    expected_paise: int


@dataclass(frozen=True)
class PreparedOrderException:
    decision: OrderDecision
    proof: ProofObject


def without_metadata(row: dict) -> dict:
    return {key: value for key, value in row.items() if key not in {"provenance", "raw_hash"}}


def source_reference(table: str, row: dict) -> SourceReference:
    return SourceReference(table=table, id=row["raw_record_id"], raw_hash=row["raw_hash"])


def sort_source_references(references: Iterable[SourceReference]) -> tuple[SourceReference, ...]:
    unique: dict[tuple[str, str, str], SourceReference] = {}
    for reference in references:
        key = (reference.table, reference.id, reference.raw_hash)
        unique.setdefault(key, reference)
    return tuple(sorted(unique.values(), key=lambda item: (item.table, item.id, item.raw_hash)))


def configuration_values(configuration: ConfigurationBundle) -> dict[str, int]:
    return configuration.values.as_dict()


def policy_from_configuration(configuration: ConfigurationBundle) -> ReconciliationPolicyV2:
    values = configuration_values(configuration)
    return ReconciliationPolicyV2(**values)


def close_scope_expected_paise(settlement: Settlement, decision: ReconciliationDecision) -> int:
    if settlement.status.casefold() in NON_PROCESSABLE_STATUSES:
        return 0
    return decision.expected_paise


def score_settlement_evidence(decision: ReconciliationDecision) -> int:
    evidence = decision.evidence
    score = 0
    score += 45 if evidence.utr_exact else 0
    score += 25 if evidence.amount_exact else 0
    score += 20 if evidence.settlement_ledger_consistent else 0
    score += 10 if evidence.temporal_consistency else 0
    score -= 40 if evidence.candidate_count > 1 else 0
    return max(0, min(100, score))


def unresolved_reason(decision: Decision, reasons: tuple[str, ...]) -> str | None:
    if decision in {Decision.UNRESOLVED, Decision.REFUSED, Decision.SYSTEM_ERROR}:
        return reasons[-1]
    return None


def missing_ledger_decision(settlement: Settlement) -> ReconciliationDecision:
    return ReconciliationDecision(
        status=Decision.SYSTEM_ERROR,
        exception_type=None,
        evidence=MatchEvidence(
            utr_exact=False,
            amount_exact=False,
            settlement_ledger_consistent=False,
            temporal_consistency=False,
            candidate_count=0,
            amount_delta_paise=0,
        ),
        expected_paise=settlement.amount_paise,
        observed_paise=None,
        observed_bank_ref=None,
        reasons=("Settlement has no Recon ledger rows in the selected source snapshot",),
    )


def evaluate_order_payment(order: MerchantOrder, payment_rows: Sequence[ReconRow]) -> OrderDecision | None:
    if detect_order_exception(order, payment_rows) is None:
        return None
    matched_rows = [row for row in payment_rows if row.type == "payment" and row.order_id == order.order_id]
    settled_payment_paise = sum(row.credit_paise for row in matched_rows)
    excess_payment_paise = max(0, settled_payment_paise - order.amount_paid_paise)
    if excess_payment_paise == 0:
        return None
    return OrderDecision(
        status=Decision.REVIEW_REQUIRED,
        exception_type=detect_order_exception(order, payment_rows),
        payment_row_count=len(matched_rows),
        settled_payment_paise=settled_payment_paise,
        excess_payment_paise=excess_payment_paise,
        reasons=(
            "Settled payment rows for this order exceed the captured order payment amount",
            "Multiple settled payment attempts must be reviewed as a separate order exception",
        ),
    )


def settlement_material_v2(
    inputs: dict,
    settlement: Settlement,
    decision: ReconciliationDecision,
    context: EvaluationContext,
) -> DecisionMaterial:
    expected_paise = close_scope_expected_paise(settlement, decision)
    return DecisionMaterial(
        subject=ProofSubject(subject_type=SubjectType.SETTLEMENT, subject_id=settlement.settlement_id),
        rule_name=SETTLEMENT_RULE_NAME,
        rule_version=SETTLEMENT_RULE_VERSION_V2,
        configuration=context.configuration,
        status=decision.status,
        source_rows=tuple(SourceReference.model_validate(item) for item in inputs["source_rows"]),
        evidence_inputs=inputs,
        evaluated_at=context.evaluated_at,
        formula="sum(credit_paise) - sum(debit_paise), grouped by settlement_id",
        result=ProofResult(
            expected_paise=expected_paise,
            observed_paise=decision.observed_paise,
            delta_paise=(None if decision.observed_paise is None else decision.observed_paise - expected_paise),
        ),
        evidence=decision.evidence,
        decision_score=score_settlement_evidence(decision),
        decision_reasons=decision.reasons,
        classification=Classification.CALCULATED,
        exception_type=decision.exception_type,
        unresolved_reason=unresolved_reason(decision.status, decision.reasons),
    )


def legacy_material_v1(inputs: dict, settlement: Settlement, decision: ReconciliationDecision) -> dict:
    return {
        "status": decision.status.value,
        "source_rows": inputs["source_rows"],
        "inputs": inputs,
        "formula": "sum(credit_paise) - sum(debit_paise), grouped by settlement_id",
        "result": {
            "expected_paise": decision.expected_paise,
            "observed_paise": decision.observed_paise,
            "delta_paise": (
                None if decision.observed_paise is None else decision.observed_paise - decision.expected_paise
            ),
        },
        "evidence": decision.evidence.model_dump(mode="json"),
        "decision_score": score_settlement_evidence(decision),
        "decision_reasons": list(decision.reasons),
        "classification": Classification.CALCULATED.value,
        "exception_type": decision.exception_type.value if decision.exception_type else None,
        "unresolved_reason": unresolved_reason(decision.status, decision.reasons),
    }


def evaluate_proof_inputs_v1(inputs: dict) -> dict:
    ledger_rows = [ReconRow.model_validate(item) for item in inputs["ledger_rows"]]
    settlement = Settlement.model_validate(inputs["settlement"])
    bank_lines = [BankLine.model_validate(item) for item in inputs["bank_lines"]]
    now = datetime.fromisoformat(inputs["now"])
    policy = ReconciliationPolicy(**inputs["policy"])
    if ledger_rows:
        decision = match_settlement_v1(reconstruct_settlement(ledger_rows), settlement, bank_lines, now, policy)
    else:
        decision = missing_ledger_decision(settlement)
    return legacy_material_v1(inputs, settlement, decision)


def evaluate_settlement_v2(inputs: dict, context: EvaluationContext) -> DecisionMaterial:
    ledger_rows = [ReconRow.model_validate(item) for item in inputs["ledger_rows"]]
    settlement = Settlement.model_validate(inputs["settlement"])
    bank_lines = [BankLine.model_validate(item) for item in inputs["bank_lines"]]
    if ledger_rows:
        decision = match_settlement(
            reconstruct_settlement(ledger_rows),
            settlement,
            bank_lines,
            context.evaluated_at,
            policy_from_configuration(context.configuration),
        )
    else:
        decision = missing_ledger_decision(settlement)
    return settlement_material_v2(inputs, settlement, decision, context)


def order_material_v1(inputs: dict, context: EvaluationContext) -> DecisionMaterial:
    order = MerchantOrder.model_validate(inputs["order"])
    payment_rows = [ReconRow.model_validate(item) for item in inputs["payment_rows"]]
    decision = evaluate_order_payment(order, payment_rows)
    if decision is None:
        raise ValueError("order evidence does not produce an excess-payment anomaly")
    return DecisionMaterial(
        subject=ProofSubject(subject_type=SubjectType.ORDER, subject_id=order.order_id),
        rule_name=ORDER_RULE_NAME,
        rule_version=ORDER_RULE_VERSION_V1,
        configuration=context.configuration,
        status=decision.status,
        source_rows=tuple(SourceReference.model_validate(item) for item in inputs["source_rows"]),
        evidence_inputs=inputs,
        evaluated_at=context.evaluated_at,
        formula="max(0, sum(payment credit_paise for matching order rows) - order.amount_paid_paise)",
        result=ProofResult(
            expected_paise=order.amount_paid_paise,
            observed_paise=decision.settled_payment_paise,
            delta_paise=decision.excess_payment_paise,
        ),
        evidence=OrderEvidence(
            payment_row_count=decision.payment_row_count,
            settled_payment_paise=decision.settled_payment_paise,
            expected_order_payment_paise=order.amount_paid_paise,
            excess_payment_paise=decision.excess_payment_paise,
        ),
        decision_score=decision.score,
        decision_reasons=decision.reasons,
        classification=Classification.CALCULATED,
        exception_type=decision.exception_type,
        unresolved_reason=None,
    )


def evaluate_order_payment_v1(inputs: dict, context: EvaluationContext) -> DecisionMaterial:
    return order_material_v1(inputs, context)


class RunService:
    def __init__(
        self,
        database: DatabaseManager,
        sources: SourceRepository,
        snapshots: SnapshotRepository,
        proof_service: ProofService,
        observability: ObservabilityStore,
        configurations: ConfigurationRegistry,
        now: Callable[[], datetime],
    ) -> None:
        self.database = database
        self.sources = sources
        self.snapshots = snapshots
        self.proofs = proof_service
        self.observability = observability
        self.configurations = configurations
        self.now = now

    def run_snapshot(self, tenant_id: str, snapshot_id: str, *, evaluated_at: datetime | None = None) -> dict:
        if evaluated_at is not None:
            if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
                raise ValueError("evaluation time requires a timezone offset")
            evaluated_at = evaluated_at.astimezone(timezone.utc)
        started = perf_counter()
        run_id = f"run_{uuid4().hex[:16]}"
        snapshot = self.snapshots.get(tenant_id, snapshot_id)
        if snapshot is None:
            raise ValueError("source snapshot not found for tenant")
        configuration = self.configurations.current()
        if configuration is None:
            raise RuntimeError("current configuration bundle is unavailable")
        with self.database.session() as session:
            session.add(
                RunRecord(
                    id=run_id,
                    tenant_id=tenant_id,
                    source_snapshot_id=snapshot_id,
                    state="RUNNING",
                    rule_version=SETTLEMENT_RULE_VERSION_V2,
                    configuration_version=configuration.version,
                    records_processed=0,
                    expected_paise=0,
                    explained_paise=0,
                    unresolved_paise=0,
                    total_ms=0,
                    timings_json="{}",
                )
            )
        try:
            return self._execute_snapshot(tenant_id, snapshot_id, snapshot.source_ids_json, run_id, started, configuration, evaluated_at)
        except Exception as exc:
            total_ms = max(0, round((perf_counter() - started) * 1000))
            with self.database.session() as session:
                failed = session.scalar(
                    select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id)
                )
                if failed is not None:
                    failed.state = "FAILED"
                    failed.total_ms = total_ms
                    failed.timings_json = json.dumps({"failure_boundary_ms": total_ms})
            self.proofs.discard_run_cache(run_id)
            self.observability.event(
                tenant_id,
                "RUN_FAILED",
                {"state": "FAILED", "error_type": type(exc).__name__},
                run_id,
            )
            raise

    def _execute_snapshot(
        self,
        tenant_id: str,
        snapshot_id: str,
        source_ids_json: str,
        run_id: str,
        started: float,
        configuration: ConfigurationBundle,
        evaluated_at: datetime | None = None,
    ) -> dict:
        source_ids = json.loads(source_ids_json)
        timings: dict[str, int] = {}
        with measured(timings, "database_ms"):
            recon_data = self.sources.list_snapshot_records(tenant_id, source_ids, "razorpay_recon")
            settlement_data = self.sources.list_snapshot_records(tenant_id, source_ids, "settlements")
            bank_data = self.sources.list_snapshot_records(tenant_id, source_ids, "bank_statement")
            order_data = self.sources.list_snapshot_records(tenant_id, source_ids, "merchant_orders")
        with measured(timings, "normalization_ms"):
            recon_rows = [ReconRow.model_validate(without_metadata(row)) for row in recon_data]
            settlements = [Settlement.model_validate(without_metadata(row)) for row in settlement_data]
            bank_lines = [BankLine.model_validate(without_metadata(row)) for row in bank_data]
            orders = [MerchantOrder.model_validate(without_metadata(row)) for row in order_data]

        grouped_settlement_rows: dict[str, list[tuple[ReconRow, dict]]] = defaultdict(list)
        rows_by_order: dict[str, list[tuple[ReconRow, dict]]] = defaultdict(list)
        for model, raw in zip(recon_rows, recon_data, strict=True):
            if model.settlement_id:
                grouped_settlement_rows[model.settlement_id].append((model, raw))
            if model.order_id:
                rows_by_order[model.order_id].append((model, raw))

        with measured(timings, "settlement_build_ms"):
            ledgers = {
                settlement_id: reconstruct_settlement([row for row, _raw in rows])
                for settlement_id, rows in grouped_settlement_rows.items()
            }

        now = evaluated_at or self.now()
        context = EvaluationContext(configuration=configuration, evaluated_at=now)
        decisions_by_settlement: dict[str, ReconciliationDecision] = {}
        with measured(timings, "matching_ms"):
            matched_settlements = [settlement for settlement in settlements if settlement.settlement_id in ledgers]
            if matched_settlements:
                decisions_by_settlement.update(
                    allocate_settlements(
                        ledgers,
                        matched_settlements,
                        bank_lines,
                        now,
                        policy_from_configuration(configuration),
                    )
                )
            for settlement in settlements:
                if settlement.settlement_id not in decisions_by_settlement:
                    decisions_by_settlement[settlement.settlement_id] = missing_ledger_decision(settlement)

        bank_rows_by_ref = {line.bank_ref: raw for line, raw in zip(bank_lines, bank_data, strict=True)}
        bank_models_by_ref = {line.bank_ref: line for line in bank_lines}

        with measured(timings, "proof_generation_ms"):
            settlement_results = self._prepare_settlement_results(
                tenant_id,
                run_id,
                snapshot_id,
                configuration,
                context,
                settlements,
                settlement_data,
                grouped_settlement_rows,
                decisions_by_settlement,
                bank_models_by_ref,
                bank_rows_by_ref,
            )
            order_results = self._prepare_order_results(
                tenant_id,
                run_id,
                snapshot_id,
                configuration,
                context,
                orders,
                order_data,
                rows_by_order,
            )

        records_processed = len(recon_data) + len(settlement_data) + len(bank_data) + len(order_data)
        expected_paise = sum(item.expected_paise for item in settlement_results)
        explained_paise = sum(
            item.expected_paise for item in settlement_results if item.decision.status is Decision.AUTO_VERIFIED
        )
        run_state = (
            "PARTIAL"
            if any(item.decision.status is Decision.SYSTEM_ERROR for item in settlement_results)
            else "SUCCESS"
        )

        with measured(timings, "persistence_ms"):
            self._persist_run(
                tenant_id=tenant_id,
                run_id=run_id,
                snapshot_id=snapshot_id,
                run_state=run_state,
                configuration=configuration,
                settlement_results=settlement_results,
                order_results=order_results,
                records_processed=records_processed,
                expected_paise=expected_paise,
                explained_paise=explained_paise,
                total_ms=max(0, round((perf_counter() - started) * 1000)),
                timings=timings,
            )
        final_total_ms = max(0, round((perf_counter() - started) * 1000))
        with self.database.session() as session:
            run = session.scalar(
                select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id)
            )
            if run is None:
                raise RuntimeError("run lifecycle record is unavailable")
            run.total_ms = final_total_ms
            run.timings_json = json.dumps(timings, sort_keys=True)

        for stage, duration in timings.items():
            self.observability.timing(tenant_id, run_id, stage, duration, {"records_processed": records_processed})
        self.observability.event(
            tenant_id,
            "RUN_COMPLETED",
            {"state": run_state, "records_processed": records_processed},
            run_id,
        )
        return self.get_run(tenant_id, run_id)

    def _prepare_settlement_results(
        self,
        tenant_id: str,
        run_id: str,
        snapshot_id: str,
        configuration: ConfigurationBundle,
        context: EvaluationContext,
        settlements: Sequence[Settlement],
        settlement_data: Sequence[dict],
        grouped_settlement_rows: dict[str, list[tuple[ReconRow, dict]]],
        decisions_by_settlement: dict[str, ReconciliationDecision],
        bank_models_by_ref: dict[str, BankLine],
        bank_rows_by_ref: dict[str, dict],
    ) -> list[PreparedSettlementResult]:
        prepared: list[PreparedSettlementResult] = []
        for settlement, settlement_raw in zip(settlements, settlement_data, strict=True):
            settlement_rows = grouped_settlement_rows.get(settlement.settlement_id, [])
            decision = decisions_by_settlement[settlement.settlement_id]
            candidate_refs = tuple(dict.fromkeys(decision.candidate_bank_refs))
            scoped_bank_lines = [
                bank_models_by_ref[bank_ref].model_dump(mode="json", exclude={"narration"})
                for bank_ref in candidate_refs
                if bank_ref in bank_models_by_ref
            ]
            scoped_source_rows = sort_source_references(
                [
                    source_reference("settlements", settlement_raw),
                    *[source_reference("razorpay_recon", raw) for _model, raw in settlement_rows],
                    *[
                        source_reference("bank_statement", bank_rows_by_ref[bank_ref])
                        for bank_ref in candidate_refs
                        if bank_ref in bank_rows_by_ref
                    ],
                ]
            )
            inputs = {
                "settlement": settlement.model_dump(mode="json"),
                "ledger_rows": [model.model_dump(mode="json") for model, _raw in settlement_rows],
                "bank_lines": scoped_bank_lines,
                "policy": configuration_values(configuration),
                "source_rows": [reference.model_dump(mode="json") for reference in scoped_source_rows],
            }
            material = settlement_material_v2(inputs, settlement, decision, context)
            proof = self.proofs.create(
                tenant_id,
                run_id,
                snapshot_id,
                SETTLEMENT_RULE_NAME,
                SETTLEMENT_RULE_VERSION_V2,
                configuration.version,
                material,
            )
            prepared.append(
                PreparedSettlementResult(
                    settlement=settlement,
                    decision=decision,
                    proof=proof,
                    expected_paise=close_scope_expected_paise(settlement, decision),
                )
            )
        return prepared

    def _prepare_order_results(
        self,
        tenant_id: str,
        run_id: str,
        snapshot_id: str,
        configuration: ConfigurationBundle,
        context: EvaluationContext,
        orders: Sequence[MerchantOrder],
        order_data: Sequence[dict],
        rows_by_order: dict[str, list[tuple[ReconRow, dict]]],
    ) -> list[PreparedOrderException]:
        prepared: list[PreparedOrderException] = []
        for order, order_raw in zip(orders, order_data, strict=True):
            payment_pairs = [
                (model, raw)
                for model, raw in rows_by_order.get(order.order_id, [])
                if model.type == "payment" and model.order_id == order.order_id
            ]
            payment_rows = [model for model, _raw in payment_pairs]
            decision = evaluate_order_payment(order, payment_rows)
            if decision is None:
                continue
            scoped_source_rows = sort_source_references(
                [
                    source_reference("merchant_orders", order_raw),
                    *[source_reference("razorpay_recon", raw) for _model, raw in payment_pairs],
                ]
            )
            inputs = {
                "order": order.model_dump(mode="json"),
                "payment_rows": [row.model_dump(mode="json") for row in payment_rows],
                "source_rows": [reference.model_dump(mode="json") for reference in scoped_source_rows],
            }
            proof = self.proofs.create(
                tenant_id,
                run_id,
                snapshot_id,
                ORDER_RULE_NAME,
                ORDER_RULE_VERSION_V1,
                configuration.version,
                order_material_v1(inputs, context),
            )
            prepared.append(PreparedOrderException(decision=decision, proof=proof))
        return prepared

    def _persist_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        snapshot_id: str,
        run_state: str,
        configuration: ConfigurationBundle,
        settlement_results: Sequence[PreparedSettlementResult],
        order_results: Sequence[PreparedOrderException],
        records_processed: int,
        expected_paise: int,
        explained_paise: int,
        total_ms: int,
        timings: dict[str, int],
    ) -> None:
        with self.database.session() as session:
            run = session.scalar(
                select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id)
            )
            if run is None:
                raise RuntimeError("run lifecycle record is unavailable")
            run.state = run_state
            run.rule_version = SETTLEMENT_RULE_VERSION_V2
            run.configuration_version = configuration.version
            run.records_processed = records_processed
            run.expected_paise = expected_paise
            run.explained_paise = explained_paise
            run.unresolved_paise = expected_paise - explained_paise
            run.total_ms = total_ms
            run.timings_json = json.dumps(timings, sort_keys=True)
            session.flush()

            for item in settlement_results:
                session.add(
                    ReconciliationRecord(
                        id=f"recon_{uuid4().hex[:18]}",
                        tenant_id=tenant_id,
                        run_id=run_id,
                        settlement_id=item.settlement.settlement_id,
                        utr=item.settlement.utr,
                        expected_paise=item.expected_paise,
                        observed_paise=item.decision.observed_paise,
                        difference_paise=(
                            None
                            if item.decision.observed_paise is None
                            else item.decision.observed_paise - item.expected_paise
                        ),
                        evidence_json=item.decision.evidence.model_dump_json(),
                        decision=item.decision.status.value,
                        exception_type=item.decision.exception_type.value if item.decision.exception_type else None,
                        proof_id=item.proof.proof_id,
                        bank_ref=item.decision.observed_bank_ref,
                        reasons_json=json.dumps(item.decision.reasons),
                    )
                )
                session.add(
                    ProofRecord(
                        id=item.proof.proof_id,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        source_snapshot_id=snapshot_id,
                        rule_name=item.proof.rule_name,
                        rule_version=item.proof.rule_version,
                        proof_fingerprint=item.proof.proof_fingerprint,
                        payload_json=item.proof.model_dump_json(),
                    )
                )
                if item.decision.exception_type is not None and item.decision.status is not Decision.SYSTEM_ERROR:
                    session.add(
                        ExceptionRecord(
                            id=f"exc_{uuid4().hex[:18]}",
                            tenant_id=tenant_id,
                            run_id=run_id,
                            proof_id=item.proof.proof_id,
                            exception_type=item.decision.exception_type.value,
                            amount_paise=item.expected_paise,
                            state="OPEN",
                        )
                    )

            for item in order_results:
                session.add(
                    ProofRecord(
                        id=item.proof.proof_id,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        source_snapshot_id=snapshot_id,
                        rule_name=item.proof.rule_name,
                        rule_version=item.proof.rule_version,
                        proof_fingerprint=item.proof.proof_fingerprint,
                        payload_json=item.proof.model_dump_json(),
                    )
                )
                session.add(
                    ExceptionRecord(
                        id=f"exc_{uuid4().hex[:18]}",
                        tenant_id=tenant_id,
                        run_id=run_id,
                        proof_id=item.proof.proof_id,
                        exception_type=item.decision.exception_type.value,
                        amount_paise=item.decision.excess_payment_paise,
                        state="OPEN",
                    )
                )

    def get_run(self, tenant_id: str, run_id: str) -> dict:
        with self.database.session() as session:
            run = session.scalar(select(RunRecord).where(RunRecord.id == run_id, RunRecord.tenant_id == tenant_id))
            if run is None:
                raise KeyError(run_id)
            return {
                "run_id": run.id,
                "state": run.state,
                "source_snapshot_id": run.source_snapshot_id,
                "rule_version": run.rule_version,
                "configuration_version": run.configuration_version,
                "records_processed": run.records_processed,
                "expected_paise": run.expected_paise,
                "explained_paise": run.explained_paise,
                "unresolved_paise": run.unresolved_paise,
                "total_ms": run.total_ms,
                "timings": json.loads(run.timings_json),
                "created_at": run.created_at.isoformat(),
            }

    def latest_run(self, tenant_id: str) -> dict:
        with self.database.session() as session:
            run_id = session.scalar(
                select(RunRecord.id)
                .where(RunRecord.tenant_id == tenant_id)
                .order_by(RunRecord.created_at.desc())
            )
        if run_id is None:
            raise KeyError("latest")
        return self.get_run(tenant_id, run_id)

    def list_results(self, tenant_id: str, run_id: str) -> list[dict]:
        with self.database.session() as session:
            rows = list(
                session.scalars(
                    select(ReconciliationRecord).where(
                        ReconciliationRecord.tenant_id == tenant_id, ReconciliationRecord.run_id == run_id
                    ).order_by(ReconciliationRecord.settlement_id)
                )
            )
        return [
            {
                "settlement_id": row.settlement_id,
                "utr": row.utr,
                "expected_paise": row.expected_paise,
                "observed_paise": row.observed_paise,
                "difference_paise": row.difference_paise,
                "evidence": json.loads(row.evidence_json),
                "decision": row.decision,
                "exception_type": row.exception_type,
                "proof_id": row.proof_id,
                "bank_ref": row.bank_ref,
                "reasons": json.loads(row.reasons_json),
            }
            for row in rows
        ]
