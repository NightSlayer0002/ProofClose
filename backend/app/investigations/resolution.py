"""Read-only resolution briefs. Conditions explain checks, never promise outcomes."""
from app.presentation.currency import format_inr_paise

BRIEF_VERSION = "resolution-brief/v1"
CHECKS = (
    ("utr_exact", "Trace the bank reference", "Compare the provider UTR with the original bank reference. Obtain a corrected provider or bank export if either reference is incomplete."),
    ("amount_exact", "Explain the amount", "Compare net settlement and credit amounts in paise. Check refunds, fees and adjustments in the ledger; do not change an amount merely to make it match."),
    ("settlement_ledger_consistent", "Rebuild the settlement ledger", "Obtain all payment and refund entries belonging to this settlement. Their net credit must agree with the provider settlement."),
    ("temporal_consistency", "Check the posting window", "Check statement coverage and original posting dates. A timing difference is a possibility to investigate, not an established cause."),
)


def build_resolution_brief(canonical: dict, proof_ids: list[str]) -> dict | None:
    if not proof_ids or not (canonical.get("settlement_id") or canonical.get("proof_id")):
        return None
    evidence = canonical.get("evidence", {})
    decision = canonical.get("decision", canonical.get("status", "unavailable"))
    verified = decision == "AUTO_VERIFIED"
    checks = [] if verified else [
        {"predicate": key, "label": label, "detail": detail}
        for key, label, detail in CHECKS if evidence.get(key) is False
    ]
    if not verified and evidence.get("candidate_count", 0) > 1:
        checks.insert(0, {"predicate": "candidate_count", "label": "Resolve competing bank credits", "detail": "Request transaction-level bank evidence that distinguishes the candidates. Exact UTR and amount are insufficient when more than one candidate exists."})
    if not verified and evidence.get("candidate_count") == 0:
        checks.insert(0, {"predicate": "candidate_count", "label": "Obtain a traceable bank credit", "detail": "Request the bank statement covering this settlement and its posting window. If a credit is found, retain its reference, amount and date in a new source delivery."})
    if not verified and not checks:
        checks.append({"predicate": "decision", "label": "Review the recorded finding", "detail": "Open the proof and inspect its decision reasons. Request the related order or settlement evidence before recording an operator disposition."})
    uncertainty = (
        "This result verifies the selected snapshot, not every future delivery or the completeness of the bank's records."
        if verified else
        "Not auto-verified is not a confirmed loss. The proof establishes which checks failed; it does not establish whether the cause is delayed posting, incomplete exports or a genuine discrepancy."
    )
    condition = (
        "No evidence correction is indicated by this settlement result. Overall close readiness still depends on the other review items and close policy."
        if verified else
        "Preserve this proof. Import corrected or later source evidence, select a new snapshot and re-run reconciliation. Auto-verification still requires a unique, unallocated bank candidate, exact UTR and amount, ledger agreement and the configured timing checks. A human review does not rewrite the match."
    )
    if canonical.get("subject_type") == "ORDER":
        uncertainty = "An order/payment inconsistency is a review finding, not proof of a duplicate charge or a confirmed loss. Check which payment entries actually belong to the order."
        condition = "Preserve this proof. Request the order and related payment/refund records, import the corrected source delivery and re-run reconciliation. Record the human disposition separately; this order finding is not a bank-credit match."
    expected = canonical.get("expected_paise", canonical.get("result", {}).get("expected_paise"))
    expected_text = format_inr_paise(expected) if isinstance(expected, int) and not isinstance(expected, bool) else "unavailable"
    handoff = "\n".join([
        "ProofClose resolution brief (read-only)",
        f"Subject: {canonical.get('settlement_id', canonical.get('subject_id', 'selected proof'))}",
        f"Recorded decision: {decision}", f"Expected: {expected_text}",
        "Evidence to request:", *[f"- {item['label']}: {item['detail']}" for item in checks],
        uncertainty, condition, "Proof references: " + ", ".join(proof_ids),
        "Brief version: " + BRIEF_VERSION,
    ])
    return {"version": BRIEF_VERSION, "checks_needed": checks, "uncertainty": uncertainty, "recheck_condition": condition, "handoff_text": handoff}


def explanation_options(canonical: dict, brief: dict | None) -> dict[str, str]:
    """Only these server-authored, conditionally applicable paragraphs reach the model."""
    options: dict[str, str] = {}
    if brief:
        options["uncertainty"] = brief["uncertainty"]
        options["recheck"] = brief["recheck_condition"]
        for index, check in enumerate(brief["checks_needed"]):
            options[f"check_{index}"] = check["label"] + ": " + check["detail"]
    elif "unresolved_paise" in canonical:
        options["money_scope"] = "Not-auto-verified money includes settlements that need more evidence, review or posting time. It is not the same as a proven cash loss."
        options["work_order"] = "Review integrity and system errors first. Then inspect exception evidence and record a reasoned human disposition. A reviewed exception can remain unmatched financially."
        options["source_scope"] = "The answer describes the selected snapshot. To include a later bank delivery, choose it in Data sources and create a new run."
    return options
