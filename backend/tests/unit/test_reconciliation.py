from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.enums import Decision, ExceptionType
from app.domain.models import BankLine, MatchEvidence, MerchantOrder, ReconRow, Settlement
from app.reconciliation.allocation import allocate_settlements
from app.reconciliation.configuration import CONFIGURATION_BUNDLE_V2, ConfigurationRegistry, configuration_bundle_for
from app.reconciliation.engine import detect_order_exception, match_settlement, reconstruct_settlement
from app.reconciliation.rules import ReconciliationPolicyV2


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
UNSET = object()


def recon(
    entity_id: str,
    credit: int,
    *,
    settlement_id: str = "setl_1",
    settlement_utr: str | None = "UTR1",
    debit: int = 0,
    order_id: str | None = "order_1",
) -> ReconRow:
    return ReconRow(
        tenant_id="demo",
        source_id="src_recon",
        raw_record_id=f"raw_{entity_id}",
        entity_id=entity_id,
        type="refund" if debit else "payment",
        credit_paise=credit,
        debit_paise=debit,
        amount_paise=credit or debit,
        settlement_id=settlement_id,
        settlement_utr=settlement_utr,
        order_id=order_id,
        created_at=NOW - timedelta(hours=12),
        settled_at=NOW - timedelta(hours=2),
    )


def settlement(
    settlement_id: str = "setl_1",
    *,
    amount: int = 475_000,
    utr: str | None = "UTR1",
    status: str = "processed",
    created_at: datetime | None | object = UNSET,
) -> Settlement:
    return Settlement(
        tenant_id="demo",
        source_id="src_settlement",
        raw_record_id=f"raw_{settlement_id}",
        settlement_id=settlement_id,
        amount_paise=amount,
        status=status,
        utr=utr,
        created_at=NOW - timedelta(hours=2) if created_at is UNSET else created_at,
    )


def bank(
    bank_ref: str,
    *,
    utr: str | None = "UTR1",
    amount: int = 475_000,
    value_date: datetime | None = None,
) -> BankLine:
    return BankLine(
        tenant_id="demo",
        source_id="src_bank",
        raw_record_id=f"raw_{bank_ref}",
        bank_ref=bank_ref,
        utr=utr,
        credit_amount_paise=amount,
        value_date=value_date if value_date is not None else NOW,
        narration="RAZORPAY SETTLEMENT",
    )


def ledger_for(settlement_id: str = "setl_1", amount: int = 475_000, *, utr: str | None = "UTR1"):
    return reconstruct_settlement([recon(f"pay_{settlement_id}", amount, settlement_id=settlement_id, settlement_utr=utr)])


def test_reconstructs_settlement_from_credits_minus_debits() -> None:
    """Changing the debit sign would overstate settled money."""
    ledger = reconstruct_settlement([recon("pay_1", 500_000), recon("rfnd_1", 0, debit=25_000)])
    assert ledger.credit_paise == 500_000
    assert ledger.debit_paise == 25_000
    assert ledger.net_paise == 475_000


def test_configuration_registry_resolves_exact_versions_and_current_bundle() -> None:
    """The active configuration must be explicit so historical proofs can name exact policy values."""
    registry = ConfigurationRegistry()
    registry.register(CONFIGURATION_BUNDLE_V2)
    registry.set_current("2.0")

    resolved = registry.resolve("2.0")
    assert resolved == CONFIGURATION_BUNDLE_V2
    assert registry.current() == CONFIGURATION_BUNDLE_V2
    assert resolved.values == {
        "pending_hours": 3,
        "bank_match_window_hours": 48,
        "early_bank_tolerance_hours": 2,
        "future_clock_skew_minutes": 5,
    }
    assert registry.resolve("1.0") is None


def test_v2_policy_constructs_and_round_trips_with_exact_v2_keys_only() -> None:
    """The v2 policy contract must be standalone instead of accepting the legacy window key."""
    policy = ReconciliationPolicyV2(
        pending_hours=3,
        bank_match_window_hours=48,
        early_bank_tolerance_hours=2,
        future_clock_skew_minutes=5,
    )

    assert ReconciliationPolicyV2(**asdict(policy)) == policy
    assert configuration_bundle_for(policy).values == {
        "pending_hours": 3,
        "bank_match_window_hours": 48,
        "early_bank_tolerance_hours": 2,
        "future_clock_skew_minutes": 5,
    }
    assert "amount_candidate_window_hours" not in configuration_bundle_for(policy).values
    with pytest.raises(TypeError):
        ReconciliationPolicyV2(amount_candidate_window_hours=48)


def test_configuration_bundle_and_registry_values_are_immutable_from_callers() -> None:
    """Configuration values must not change through constructor inputs or registry lookups."""
    source_values = {
        "pending_hours": 3,
        "bank_match_window_hours": 48,
        "early_bank_tolerance_hours": 2,
        "future_clock_skew_minutes": 5,
    }
    bundle = CONFIGURATION_BUNDLE_V2.model_copy(deep=True)
    direct = configuration_bundle_for(ReconciliationPolicyV2(**source_values))
    registry = ConfigurationRegistry()
    registry.register(bundle)
    registry.set_current("2.0")
    resolved = registry.resolve("2.0")
    current = registry.current()

    source_values["pending_hours"] = 99
    with pytest.raises(TypeError):
        direct.values["pending_hours"] = 99
    with pytest.raises(TypeError):
        resolved.values["pending_hours"] = 99
    with pytest.raises(TypeError):
        current.values["pending_hours"] = 99

    assert direct.values["pending_hours"] == 3
    assert resolved.values["pending_hours"] == 3
    assert current.values["pending_hours"] == 3
    assert registry.resolve("2.0").values == {
        "pending_hours": 3,
        "bank_match_window_hours": 48,
        "early_bank_tolerance_hours": 2,
        "future_clock_skew_minutes": 5,
    }


def test_supports_auto_verification_requires_temporal_consistency() -> None:
    """A perfect amount and UTR match is still not safe without a consistent posting time."""
    evidence = MatchEvidence(
        utr_exact=True,
        amount_exact=True,
        settlement_ledger_consistent=True,
        temporal_consistency=False,
        candidate_count=1,
        amount_delta_paise=0,
    )

    assert evidence.supports_auto_verification is False


def test_exact_utr_amount_and_time_auto_verifies() -> None:
    """Only one exact, timely UTR-backed bank row can close automatically."""
    ledger = ledger_for()
    result = match_settlement(ledger, settlement(), [bank("bank_1")], NOW, ReconciliationPolicyV2())

    assert result.status is Decision.AUTO_VERIFIED
    assert result.exception_type is None
    assert result.observed_bank_ref == "bank_1"
    assert result.candidate_bank_refs == ("bank_1",)


def test_two_settlements_competing_for_one_bank_row_are_both_refused() -> None:
    """A single bank credit cannot automatically satisfy two processed settlements."""
    ledgers = {
        "setl_1": ledger_for("setl_1", 475_000, utr="SHARED"),
        "setl_2": ledger_for("setl_2", 475_000, utr="SHARED"),
    }
    settlements = [
        settlement("setl_1", utr="SHARED"),
        settlement("setl_2", utr="SHARED"),
    ]

    decisions = allocate_settlements(ledgers, settlements, [bank("bank_1", utr="shared")], NOW, ReconciliationPolicyV2())

    assert decisions["setl_1"].status is Decision.REFUSED
    assert decisions["setl_2"].status is Decision.REFUSED
    assert decisions["setl_1"].exception_type is ExceptionType.AMBIGUOUS_MATCH
    assert decisions["setl_2"].exception_type is ExceptionType.AMBIGUOUS_MATCH
    assert decisions["setl_1"].candidate_bank_refs == ("bank_1",)
    assert decisions["setl_2"].candidate_bank_refs == ("bank_1",)


def test_duplicate_same_utr_rows_are_refused_with_sorted_candidates() -> None:
    """Multiple bank rows with one settlement UTR must stay ambiguous for review."""
    ledger = ledger_for()
    result = match_settlement(
        ledger,
        settlement(),
        [bank("bank_2"), bank("bank_1")],
        NOW,
        ReconciliationPolicyV2(),
    )

    assert result.status is Decision.REFUSED
    assert result.exception_type is ExceptionType.AMBIGUOUS_MATCH
    assert result.evidence.candidate_count == 2
    assert result.candidate_bank_refs == ("bank_1", "bank_2")


def test_unique_same_utr_wrong_amount_requires_review() -> None:
    """A unique UTR hit still needs review when the bank amount disagrees with the settlement ledger."""
    ledger = ledger_for()
    result = match_settlement(ledger, settlement(), [bank("bank_1", amount=470_000)], NOW, ReconciliationPolicyV2())

    assert result.status is Decision.REVIEW_REQUIRED
    assert result.exception_type is ExceptionType.SETTLEMENT_BANK_AMOUNT_MISMATCH
    assert result.observed_bank_ref == "bank_1"
    assert result.candidate_bank_refs == ("bank_1",)


@pytest.mark.parametrize(
    ("value_date", "expected_status", "expected_exception"),
    [
        (NOW - timedelta(hours=4), Decision.REVIEW_REQUIRED, ExceptionType.BANK_TIMING_INCONSISTENCY),
        (NOW - timedelta(hours=2), Decision.AUTO_VERIFIED, None),
        (NOW + timedelta(hours=48), Decision.AUTO_VERIFIED, None),
        (NOW + timedelta(hours=48, seconds=1), Decision.REVIEW_REQUIRED, ExceptionType.BANK_TIMING_INCONSISTENCY),
    ],
)
def test_temporal_policy_enforces_early_late_and_inclusive_boundaries(
    value_date: datetime,
    expected_status: Decision,
    expected_exception: ExceptionType | None,
) -> None:
    """Posting times are inclusive on the policy edges and suspicious just beyond them."""
    ledger = ledger_for()
    created_at = NOW
    result = match_settlement(
        ledger,
        settlement(created_at=created_at),
        [bank("bank_1", value_date=value_date)],
        NOW,
        ReconciliationPolicyV2(),
    )

    assert result.status is expected_status
    assert result.exception_type is expected_exception


def test_one_amount_time_only_candidate_requires_manual_review() -> None:
    """Amount and timing alone are useful clues but never enough for auto-verification."""
    ledger = ledger_for(utr=None)
    result = match_settlement(
        ledger,
        settlement(utr=None),
        [bank("bank_1", utr="OTHER")],
        NOW,
        ReconciliationPolicyV2(),
    )

    assert result.status is Decision.REVIEW_REQUIRED
    assert result.exception_type is ExceptionType.MANUAL_BANK_MATCH_REQUIRED
    assert result.observed_bank_ref == "bank_1"
    assert result.candidate_bank_refs == ("bank_1",)


def test_multiple_amount_time_only_candidates_are_refused() -> None:
    """Without UTR evidence, multiple exact amount-time candidates must remain ambiguous."""
    ledger = ledger_for(utr=None)
    result = match_settlement(
        ledger,
        settlement(utr=None),
        [bank("bank_2", utr="OTHER"), bank("bank_1", utr=None)],
        NOW,
        ReconciliationPolicyV2(),
    )

    assert result.status is Decision.REFUSED
    assert result.exception_type is ExceptionType.AMBIGUOUS_MATCH
    assert result.candidate_bank_refs == ("bank_1", "bank_2")


def test_missing_settlement_timestamp_blocks_auto_verification() -> None:
    """A missing settlement timestamp makes timing unverifiable even when the UTR and amount match."""
    ledger = ledger_for()
    result = match_settlement(
        ledger,
        settlement(created_at=None),
        [bank("bank_1")],
        NOW,
        ReconciliationPolicyV2(),
    )

    assert result.status is Decision.REVIEW_REQUIRED
    assert result.exception_type is ExceptionType.BANK_TIMING_INCONSISTENCY
    assert result.evidence.temporal_consistency is False


def test_future_settlement_timestamp_is_reported_as_source_quality_issue() -> None:
    """A settlement dated beyond the allowed future skew is a source-data problem, not a match result."""
    ledger = ledger_for()
    result = match_settlement(
        ledger,
        settlement(created_at=NOW + timedelta(minutes=6)),
        [bank("bank_1")],
        NOW,
        ReconciliationPolicyV2(),
    )

    assert result.status is Decision.REVIEW_REQUIRED
    assert result.exception_type is ExceptionType.SOURCE_DATA_QUALITY_ISSUE
    assert result.candidate_bank_refs == ()


@pytest.mark.parametrize(
    ("status", "expected_decision", "expected_exception"),
    [
        ("pending", Decision.PENDING, None),
        ("created", Decision.PENDING, None),
        ("failed", Decision.REFUSED, ExceptionType.NON_PROCESSABLE_SETTLEMENT_STATUS),
        ("cancelled", Decision.REFUSED, ExceptionType.NON_PROCESSABLE_SETTLEMENT_STATUS),
        ("reversed", Decision.REFUSED, ExceptionType.NON_PROCESSABLE_SETTLEMENT_STATUS),
    ],
)
def test_status_policy_applies_before_bank_matching(
    status: str,
    expected_decision: Decision,
    expected_exception: ExceptionType | None,
) -> None:
    """Non-processed statuses must never close from bank evidence alone."""
    ledger = ledger_for()
    result = match_settlement(
        ledger,
        settlement(status=status),
        [bank("bank_1")],
        NOW,
        ReconciliationPolicyV2(),
    )

    assert result.status is expected_decision
    assert result.exception_type is expected_exception
    assert result.observed_bank_ref is None


def test_processed_no_match_inside_pending_window_stays_pending() -> None:
    """A processed settlement can remain pending while the posting window is still open."""
    ledger = ledger_for()
    result = match_settlement(
        ledger,
        settlement(created_at=NOW - timedelta(hours=2)),
        [],
        NOW,
        ReconciliationPolicyV2(pending_hours=3),
    )

    assert result.status is Decision.PENDING
    assert result.exception_type is None


def test_processed_no_match_outside_pending_window_is_unresolved() -> None:
    """Once the posting window expires, the missing bank credit becomes a real exception."""
    ledger = ledger_for()
    result = match_settlement(
        ledger,
        settlement(created_at=NOW - timedelta(hours=5)),
        [],
        NOW,
        ReconciliationPolicyV2(pending_hours=3),
    )

    assert result.status is Decision.UNRESOLVED
    assert result.exception_type is ExceptionType.MISSING_BANK_CREDIT


def test_ledger_mismatch_requires_review_before_bank_matching() -> None:
    """A bank credit cannot hide an inconsistent settlement ledger."""
    ledger = ledger_for(amount=470_000)
    result = match_settlement(ledger, settlement(amount=475_000), [bank("bank_1")], NOW, ReconciliationPolicyV2())

    assert result.status is Decision.REVIEW_REQUIRED
    assert result.exception_type is ExceptionType.SETTLEMENT_LEDGER_MISMATCH
    assert result.evidence.settlement_ledger_consistent is False


def test_exact_hundredfold_delta_is_classified_as_paise_rupee_mismatch() -> None:
    """A x100 unit error should stay distinct from an ordinary ledger mismatch."""
    ledger = ledger_for()
    result = match_settlement(
        ledger,
        settlement(amount=47_500_000),
        [bank("bank_1")],
        NOW,
        ReconciliationPolicyV2(),
    )

    assert result.status is Decision.REVIEW_REQUIRED
    assert result.exception_type is ExceptionType.PAISE_RUPEE_MISMATCH


def test_non_partial_order_flags_only_excess_settled_money() -> None:
    """Multiple attempts are allowed until their settled value contradicts the order."""
    from app.runs.service import evaluate_order_payment

    order = MerchantOrder(
        tenant_id="demo",
        source_id="src_orders",
        raw_record_id="raw_order",
        order_id="order_1",
        amount_paise=100_000,
        amount_paid_paise=100_000,
        partial_payment=False,
    )

    assert detect_order_exception(order, [recon("pay_1", 50_000), recon("pay_2", 50_000)]) is None
    assert evaluate_order_payment(order, [recon("pay_1", 50_000), recon("pay_2", 50_000)]) is None
    assert detect_order_exception(order, [recon("pay_1", 100_000), recon("pay_2", 100_000)]) is ExceptionType.UNEXPECTED_MULTIPLE_SETTLED_PAYMENTS
    decision = evaluate_order_payment(order, [recon("pay_1", 100_000), recon("pay_2", 100_000)])

    assert decision is not None
    assert decision.status is Decision.REVIEW_REQUIRED
    assert decision.exception_type is ExceptionType.UNEXPECTED_MULTIPLE_SETTLED_PAYMENTS
    assert decision.settled_payment_paise == 200_000
    assert decision.excess_payment_paise == 100_000
    assert decision.payment_row_count == 2


def test_partial_payment_orders_do_not_raise_order_excess_anomalies() -> None:
    """Partial-payment orders are out of scope for the excess-payment exception rule."""
    from app.runs.service import evaluate_order_payment

    order = MerchantOrder(
        tenant_id="demo",
        source_id="src_orders",
        raw_record_id="raw_partial_order",
        order_id="order_partial",
        amount_paise=100_000,
        amount_paid_paise=100_000,
        partial_payment=True,
    )

    assert detect_order_exception(order, [recon("pay_1", 100_000), recon("pay_2", 100_000, order_id="order_partial")]) is None
    assert evaluate_order_payment(
        order,
        [recon("pay_1", 100_000, order_id="order_partial"), recon("pay_2", 100_000, order_id="order_partial")],
    ) is None
