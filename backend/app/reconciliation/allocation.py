from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from app.domain.enums import Decision, ExceptionType
from app.domain.models import BankLine, MatchEvidence, Settlement
from app.reconciliation.engine import ReconciliationDecision, SettlementLedger, normalize_utr
from app.reconciliation.rules import ReconciliationPolicyV2


NON_PROCESSABLE_STATUSES = frozenset({"failed", "cancelled", "reversed"})
PENDING_STATUSES = frozenset({"pending", "created"})


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _base_evidence(
    ledger: SettlementLedger,
    settlement: Settlement,
    *,
    candidate_count: int = 0,
    utr_exact: bool = False,
    amount_exact: bool = False,
    temporal_consistency: bool = False,
    amount_delta_paise: int | None = None,
) -> MatchEvidence:
    ledger_delta = ledger.net_paise - settlement.amount_paise
    return MatchEvidence(
        utr_exact=utr_exact,
        amount_exact=amount_exact,
        settlement_ledger_consistent=ledger_delta == 0,
        temporal_consistency=temporal_consistency,
        candidate_count=candidate_count,
        amount_delta_paise=ledger_delta if amount_delta_paise is None else amount_delta_paise,
    )


def _decision(
    status: Decision,
    exception_type: ExceptionType | None,
    evidence: MatchEvidence,
    ledger: SettlementLedger,
    *,
    observed_paise: int | None = None,
    observed_bank_ref: str | None = None,
    reasons: tuple[str, ...],
    candidate_bank_refs: tuple[str, ...] = (),
) -> ReconciliationDecision:
    return ReconciliationDecision(
        status=status,
        exception_type=exception_type,
        evidence=evidence,
        expected_paise=ledger.net_paise,
        observed_paise=observed_paise,
        observed_bank_ref=observed_bank_ref,
        reasons=reasons,
        candidate_bank_refs=candidate_bank_refs,
    )


def _age_hours(created_at: datetime | None, now: datetime) -> float:
    if created_at is None:
        return float("inf")
    return (_coerce_utc(now) - _coerce_utc(created_at)).total_seconds() / 3600


def _future_cutoff(now: datetime, policy: ReconciliationPolicyV2) -> datetime:
    return _coerce_utc(now) + timedelta(minutes=policy.future_clock_skew_minutes)


def _bank_time_is_consistent(
    settlement_created_at: datetime | None,
    bank_value_date: datetime | None,
    policy: ReconciliationPolicyV2,
) -> bool:
    if settlement_created_at is None or bank_value_date is None:
        return False
    created_at = _coerce_utc(settlement_created_at)
    value_date = _coerce_utc(bank_value_date)
    early_hours = policy.early_bank_tolerance_hours
    late_hours = policy.bank_match_window_hours
    earliest = created_at - timedelta(hours=early_hours)
    latest = created_at + timedelta(hours=late_hours)
    return earliest <= value_date <= latest


def allocate_settlements(
    ledgers: Mapping[str, SettlementLedger],
    settlements: Sequence[Settlement],
    bank_lines: Sequence[BankLine],
    now: datetime,
    policy: ReconciliationPolicyV2,
) -> dict[str, ReconciliationDecision]:
    indexed_bank_lines: dict[str, list[BankLine]] = defaultdict(list)
    for line in bank_lines:
        normalized = normalize_utr(line.utr)
        if normalized is not None:
            indexed_bank_lines[normalized].append(line)

    decisions: dict[str, ReconciliationDecision] = {}
    eligible_pairs: list[tuple[SettlementLedger, Settlement]] = []
    same_utr_candidates: dict[str, tuple[BankLine, ...]] = {}
    owners_by_bank_ref: dict[str, set[str]] = defaultdict(set)

    for settlement in settlements:
        ledger = ledgers.get(settlement.settlement_id)
        if ledger is None:
            raise ValueError(f"missing ledger for settlement {settlement.settlement_id}")
        if ledger.settlement_id != settlement.settlement_id:
            raise ValueError("ledger and Settlement entity identifiers differ")

        if settlement.created_at is not None and _coerce_utc(settlement.created_at) > _future_cutoff(now, policy):
            evidence = _base_evidence(ledger, settlement)
            decisions[settlement.settlement_id] = _decision(
                Decision.REVIEW_REQUIRED,
                ExceptionType.SOURCE_DATA_QUALITY_ISSUE,
                evidence,
                ledger,
                reasons=("Settlement timestamp is later than the permitted future clock skew",),
            )
            continue

        if settlement.status in PENDING_STATUSES:
            evidence = _base_evidence(ledger, settlement)
            decisions[settlement.settlement_id] = _decision(
                Decision.PENDING,
                None,
                evidence,
                ledger,
                reasons=("Settlement is not yet processed and is ineligible for bank matching",),
            )
            continue

        if settlement.status in NON_PROCESSABLE_STATUSES:
            evidence = _base_evidence(ledger, settlement)
            decisions[settlement.settlement_id] = _decision(
                Decision.REFUSED,
                ExceptionType.NON_PROCESSABLE_SETTLEMENT_STATUS,
                evidence,
                ledger,
                reasons=("Settlement status is non-processable for bank reconciliation",),
            )
            continue

        ledger_delta = ledger.net_paise - settlement.amount_paise
        if ledger_delta != 0:
            hundredfold = (
                ledger.net_paise != 0
                and settlement.amount_paise != 0
                and (
                    settlement.amount_paise == ledger.net_paise * 100
                    or ledger.net_paise == settlement.amount_paise * 100
                )
            )
            evidence = _base_evidence(ledger, settlement)
            decisions[settlement.settlement_id] = _decision(
                Decision.REVIEW_REQUIRED,
                ExceptionType.PAISE_RUPEE_MISMATCH if hundredfold else ExceptionType.SETTLEMENT_LEDGER_MISMATCH,
                evidence,
                ledger,
                reasons=(
                    (
                        "Settlement and reconstructed ledger differ by an exact x100 unit ratio",
                    )
                    if hundredfold
                    else ("Reconstructed Recon ledger differs from the Settlement entity",)
                ),
            )
            continue

        eligible_pairs.append((ledger, settlement))
        expected_utr = normalize_utr(settlement.utr)
        candidates = tuple(sorted(indexed_bank_lines.get(expected_utr, ()), key=lambda line: line.bank_ref)) if expected_utr else ()
        same_utr_candidates[settlement.settlement_id] = candidates
        for candidate in candidates:
            owners_by_bank_ref[candidate.bank_ref].add(settlement.settlement_id)

    sorted_bank_lines = tuple(sorted(bank_lines, key=lambda line: line.bank_ref))

    for ledger, settlement in eligible_pairs:
        candidates = same_utr_candidates[settlement.settlement_id]
        candidate_refs = tuple(candidate.bank_ref for candidate in candidates)

        if candidates:
            if len(candidates) > 1 or any(len(owners_by_bank_ref[candidate.bank_ref]) > 1 for candidate in candidates):
                evidence = _base_evidence(
                    ledger,
                    settlement,
                    candidate_count=len(candidates),
                    utr_exact=True,
                    amount_exact=all(candidate.credit_amount_paise == ledger.net_paise for candidate in candidates),
                    temporal_consistency=all(
                        _bank_time_is_consistent(settlement.created_at, candidate.value_date, policy)
                        for candidate in candidates
                    ),
                    amount_delta_paise=0,
                )
                decisions[settlement.settlement_id] = _decision(
                    Decision.REFUSED,
                    ExceptionType.AMBIGUOUS_MATCH,
                    evidence,
                    ledger,
                    reasons=("Same-UTR bank evidence is ambiguous across candidate rows or claimants",),
                    candidate_bank_refs=candidate_refs,
                )
                continue

            candidate = candidates[0]
            amount_delta = candidate.credit_amount_paise - ledger.net_paise
            temporal_consistency = _bank_time_is_consistent(settlement.created_at, candidate.value_date, policy)
            evidence = _base_evidence(
                ledger,
                settlement,
                candidate_count=1,
                utr_exact=True,
                amount_exact=amount_delta == 0,
                temporal_consistency=temporal_consistency,
                amount_delta_paise=amount_delta,
            )
            if amount_delta != 0:
                decisions[settlement.settlement_id] = _decision(
                    Decision.REVIEW_REQUIRED,
                    ExceptionType.SETTLEMENT_BANK_AMOUNT_MISMATCH,
                    evidence,
                    ledger,
                    observed_paise=candidate.credit_amount_paise,
                    observed_bank_ref=candidate.bank_ref,
                    reasons=("UTR exact but bank amount differs from the settlement ledger",),
                    candidate_bank_refs=candidate_refs,
                )
                continue
            if not temporal_consistency:
                decisions[settlement.settlement_id] = _decision(
                    Decision.REVIEW_REQUIRED,
                    ExceptionType.BANK_TIMING_INCONSISTENCY,
                    evidence,
                    ledger,
                    observed_paise=candidate.credit_amount_paise,
                    observed_bank_ref=candidate.bank_ref,
                    reasons=("UTR and amount match, but the bank posting time is inconsistent",),
                    candidate_bank_refs=candidate_refs,
                )
                continue
            decisions[settlement.settlement_id] = _decision(
                Decision.AUTO_VERIFIED,
                None,
                evidence,
                ledger,
                observed_paise=candidate.credit_amount_paise,
                observed_bank_ref=candidate.bank_ref,
                reasons=("UTR exact", "Amount exact", "Settlement reconstruction consistent", "Unique bank candidate"),
                candidate_bank_refs=candidate_refs,
            )
            continue

        amount_candidates = tuple(
            line
            for line in sorted_bank_lines
            if line.credit_amount_paise == ledger.net_paise
            and _bank_time_is_consistent(settlement.created_at, line.value_date, policy)
        )
        candidate_refs = tuple(candidate.bank_ref for candidate in amount_candidates)
        if len(amount_candidates) > 1:
            evidence = _base_evidence(
                ledger,
                settlement,
                candidate_count=len(amount_candidates),
                amount_exact=True,
                temporal_consistency=True,
                amount_delta_paise=0,
            )
            decisions[settlement.settlement_id] = _decision(
                Decision.REFUSED,
                ExceptionType.AMBIGUOUS_MATCH,
                evidence,
                ledger,
                reasons=("Multiple amount-and-time bank candidates remain without UTR evidence",),
                candidate_bank_refs=candidate_refs,
            )
            continue
        if len(amount_candidates) == 1:
            candidate = amount_candidates[0]
            evidence = _base_evidence(
                ledger,
                settlement,
                candidate_count=1,
                amount_exact=True,
                temporal_consistency=True,
                amount_delta_paise=0,
            )
            decisions[settlement.settlement_id] = _decision(
                Decision.REVIEW_REQUIRED,
                ExceptionType.MANUAL_BANK_MATCH_REQUIRED,
                evidence,
                ledger,
                observed_paise=candidate.credit_amount_paise,
                observed_bank_ref=candidate.bank_ref,
                reasons=("One exact amount-and-time bank candidate was found without same-UTR evidence",),
                candidate_bank_refs=candidate_refs,
            )
            continue

        evidence = _base_evidence(ledger, settlement)
        if _age_hours(settlement.created_at, now) <= policy.pending_hours:
            decisions[settlement.settlement_id] = _decision(
                Decision.PENDING,
                None,
                evidence,
                ledger,
                reasons=("Settlement is inside the configured bank posting window",),
            )
            continue
        decisions[settlement.settlement_id] = _decision(
            Decision.UNRESOLVED,
            ExceptionType.MISSING_BANK_CREDIT,
            evidence,
            ledger,
            reasons=("Processed settlement is outside the bank posting window", "No supported bank candidate"),
        )

    return decisions
