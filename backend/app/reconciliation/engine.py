from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.domain.enums import Decision, ExceptionType
from app.domain.models import BankLine, MatchEvidence, MerchantOrder, ReconRow, Settlement
from app.reconciliation.rules import ReconciliationPolicy, ReconciliationPolicyV2


@dataclass(frozen=True)
class SettlementLedger:
    settlement_id: str
    rows: tuple[ReconRow, ...]
    credit_paise: int
    debit_paise: int
    net_paise: int


@dataclass(frozen=True)
class ReconciliationDecision:
    status: Decision
    exception_type: ExceptionType | None
    evidence: MatchEvidence
    expected_paise: int
    observed_paise: int | None
    observed_bank_ref: str | None
    reasons: tuple[str, ...]
    candidate_bank_refs: tuple[str, ...] = ()


def normalize_utr(value: str | None) -> str | None:
    if not value:
        return None
    normalized = "".join(character for character in value.upper() if character.isalnum())
    return normalized or None


def reconstruct_settlement(rows: Sequence[ReconRow]) -> SettlementLedger:
    if not rows:
        raise ValueError("a settlement ledger needs at least one Recon row")
    settlement_ids = {row.settlement_id for row in rows}
    if None in settlement_ids or len(settlement_ids) != 1:
        raise ValueError("all Recon rows must share one settlement_id")
    credits = sum(row.credit_paise for row in rows)
    debits = sum(row.debit_paise for row in rows)
    return SettlementLedger(str(rows[0].settlement_id), tuple(rows), credits, debits, credits - debits)


def detect_order_exception(order: MerchantOrder, payment_rows: Sequence[ReconRow]) -> ExceptionType | None:
    if order.partial_payment:
        return None
    settled_credit = sum(
        row.credit_paise for row in payment_rows if row.type == "payment" and row.order_id == order.order_id
    )
    if settled_credit > order.amount_paid_paise:
        return ExceptionType.UNEXPECTED_MULTIPLE_SETTLED_PAYMENTS
    return None


def _age_hours_v1(created_at: datetime | None, now: datetime) -> float:
    if created_at is None:
        return float("inf")
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created_at).total_seconds() / 3600)


def _base_evidence(ledger: SettlementLedger, settlement: Settlement, candidate_count: int = 0) -> MatchEvidence:
    ledger_delta = ledger.net_paise - settlement.amount_paise
    return MatchEvidence(
        utr_exact=False,
        amount_exact=False,
        settlement_ledger_consistent=ledger_delta == 0,
        temporal_consistency=False,
        candidate_count=candidate_count,
        amount_delta_paise=ledger_delta,
    )


def match_settlement(
    ledger: SettlementLedger,
    settlement: Settlement,
    bank_lines: Sequence[BankLine],
    now: datetime,
    policy: ReconciliationPolicyV2,
) -> ReconciliationDecision:
    if ledger.settlement_id != settlement.settlement_id:
        raise ValueError("ledger and Settlement entity identifiers differ")
    from app.reconciliation.allocation import allocate_settlements

    return allocate_settlements(
        {ledger.settlement_id: ledger},
        [settlement],
        bank_lines,
        now,
        policy,
    )[settlement.settlement_id]


def match_settlement_v1(
    ledger: SettlementLedger,
    settlement: Settlement,
    bank_lines: Sequence[BankLine],
    now: datetime,
    policy: ReconciliationPolicy,
) -> ReconciliationDecision:
    if ledger.settlement_id != settlement.settlement_id:
        raise ValueError("ledger and Settlement entity identifiers differ")
    ledger_delta = ledger.net_paise - settlement.amount_paise
    if ledger_delta != 0:
        evidence = _base_evidence(ledger, settlement)
        hundredfold = (
            ledger.net_paise != 0
            and settlement.amount_paise != 0
            and (
                settlement.amount_paise == ledger.net_paise * 100
                or ledger.net_paise == settlement.amount_paise * 100
            )
        )
        exception_type = (
            ExceptionType.PAISE_RUPEE_MISMATCH
            if hundredfold
            else ExceptionType.SETTLEMENT_LEDGER_MISMATCH
        )
        return ReconciliationDecision(
            Decision.REVIEW_REQUIRED,
            exception_type,
            evidence,
            ledger.net_paise,
            None,
            None,
            (
                "Settlement and reconstructed ledger differ by an exact ×100 unit ratio"
                if hundredfold
                else "Reconstructed Recon ledger differs from the Settlement entity",
            ),
        )

    expected_utr = normalize_utr(settlement.utr)
    utr_candidates = [line for line in bank_lines if expected_utr and normalize_utr(line.utr) == expected_utr]
    if len(utr_candidates) > 1:
        evidence = MatchEvidence(
            utr_exact=True,
            amount_exact=all(line.credit_amount_paise == ledger.net_paise for line in utr_candidates),
            settlement_ledger_consistent=True,
            temporal_consistency=True,
            candidate_count=len(utr_candidates),
            amount_delta_paise=0,
        )
        return ReconciliationDecision(
            Decision.REFUSED,
            ExceptionType.AMBIGUOUS_MATCH,
            evidence,
            ledger.net_paise,
            None,
            None,
            (f"{len(utr_candidates)} bank rows share the settlement UTR", "Automatic selection refused"),
        )
    if len(utr_candidates) == 1:
        candidate = utr_candidates[0]
        delta = candidate.credit_amount_paise - ledger.net_paise
        evidence = MatchEvidence(
            utr_exact=True,
            amount_exact=delta == 0,
            settlement_ledger_consistent=True,
            temporal_consistency=True,
            candidate_count=1,
            amount_delta_paise=delta,
        )
        if evidence.supports_auto_verification:
            return ReconciliationDecision(
                Decision.AUTO_VERIFIED,
                None,
                evidence,
                ledger.net_paise,
                candidate.credit_amount_paise,
                candidate.bank_ref,
                ("UTR exact", "Amount exact", "Settlement reconstruction consistent", "Unique bank candidate"),
            )
        return ReconciliationDecision(
            Decision.REVIEW_REQUIRED,
            ExceptionType.SETTLEMENT_LEDGER_MISMATCH,
            evidence,
            ledger.net_paise,
            candidate.credit_amount_paise,
            candidate.bank_ref,
            ("UTR exact but bank amount differs",),
        )

    amount_candidates = [
        line
        for line in bank_lines
        if line.credit_amount_paise == ledger.net_paise
        and line.value_date is not None
        and abs(_age_hours_v1(line.value_date, settlement.created_at or now)) <= policy.amount_candidate_window_hours
    ]
    if len(amount_candidates) > 1:
        evidence = MatchEvidence(
            utr_exact=False,
            amount_exact=True,
            settlement_ledger_consistent=True,
            temporal_consistency=True,
            candidate_count=len(amount_candidates),
            amount_delta_paise=0,
        )
        return ReconciliationDecision(
            Decision.REFUSED,
            ExceptionType.AMBIGUOUS_MATCH,
            evidence,
            ledger.net_paise,
            None,
            None,
            (f"{len(amount_candidates)} amount-and-time candidates remain", "Missing reliable UTR evidence"),
        )
    if len(amount_candidates) == 1:
        candidate = amount_candidates[0]
        evidence = MatchEvidence(
            utr_exact=False,
            amount_exact=True,
            settlement_ledger_consistent=True,
            temporal_consistency=True,
            candidate_count=1,
            amount_delta_paise=0,
        )
        return ReconciliationDecision(
            Decision.REVIEW_REQUIRED,
            None,
            evidence,
            ledger.net_paise,
            candidate.credit_amount_paise,
            candidate.bank_ref,
            ("One amount-and-time candidate found", "UTR evidence unavailable; human review required"),
        )

    evidence = _base_evidence(ledger, settlement)
    if settlement.status == "processed" and _age_hours_v1(settlement.created_at, now) <= policy.pending_hours:
        return ReconciliationDecision(
            Decision.PENDING,
            None,
            evidence,
            ledger.net_paise,
            None,
            None,
            ("Settlement is inside the configured bank posting window",),
        )
    return ReconciliationDecision(
        Decision.UNRESOLVED,
        ExceptionType.MISSING_BANK_CREDIT,
        evidence,
        ledger.net_paise,
        None,
        None,
        ("Processed settlement is outside the bank posting window", "No supported bank candidate"),
    )
