"""Server-owned, read-only operational guidance for evidence exceptions."""

from app.investigations.contracts import RecommendedAction


_PLAYBOOKS: dict[str, tuple[RecommendedAction, ...]] = {
    "MISSING_BANK_CREDIT": (
        RecommendedAction(code="CHECK_STATEMENT_WINDOW", label="Check the statement window", detail="Confirm the bank statement covers the settlement posting window."),
        RecommendedAction(code="OBTAIN_BANK_EVIDENCE", label="Obtain bank evidence", detail="Ask for the missing bank statement or posting record before making a decision."),
        RecommendedAction(code="RERUN_RECONCILIATION", label="Rerun reconciliation", detail="Rerun after the source evidence is accepted so the proof is rebuilt deterministically."),
    ),
    "AMBIGUOUS_MATCH": (
        RecommendedAction(code="COMPARE_CANDIDATES", label="Compare the candidates", detail="Review each bank candidate and identify the single supported credit, if one exists."),
        RecommendedAction(code="CONFIRM_UTR", label="Confirm the UTR", detail="Match the UTR and amount against the original bank evidence."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="When no unique candidate can be established, record an unresolved disposition. This marks the review complete and does not change the proof."),
    ),
    "UTR_MISMATCH": (
        RecommendedAction(code="CONFIRM_UTR", label="Confirm the UTR", detail="Check the merchant UTR against the bank reference without changing the source record."),
        RecommendedAction(code="OBTAIN_BANK_EVIDENCE", label="Obtain bank evidence", detail="Request the authoritative posting detail if the reference is incomplete."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="Record the operator decision only after reviewing the evidence."),
    ),
    "SETTLEMENT_BANK_AMOUNT_MISMATCH": (
        RecommendedAction(code="COMPARE_AMOUNTS", label="Compare the amounts", detail="Compare the integer-paise values in the settlement and bank records."),
        RecommendedAction(code="CHECK_FEES_OR_ADJUSTMENTS", label="Check adjustments", detail="Look for a documented fee or adjustment in the source evidence."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="If the amount difference cannot be explained, record an unresolved disposition. This marks the review complete and does not change the proof."),
    ),
    "BANK_TIMING_INCONSISTENCY": (
        RecommendedAction(code="CHECK_POSTING_WINDOW", label="Check posting timing", detail="Confirm whether the bank credit is inside the configured timing window."),
        RecommendedAction(code="WAIT_FOR_POSTING", label="Wait for posting", detail="A pending item may need a later bank posting before it can be resolved."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="Record an operator decision only with supporting evidence."),
    ),
    "SETTLEMENT_LEDGER_MISMATCH": (
        RecommendedAction(code="CHECK_LEDGER_TOTAL", label="Check the ledger total", detail="Compare the settlement ledger total with the source snapshot."),
        RecommendedAction(code="TRACE_SOURCE_LINEAGE", label="Trace source lineage", detail="Open the proof sources and verify the relevant rows and hashes."),
        RecommendedAction(code="ESCALATE_DATA_QUALITY", label="Escalate data quality", detail="Escalate when the source data cannot explain the difference."),
    ),
    "SOURCE_DATA_QUALITY_ISSUE": (
        RecommendedAction(code="REVIEW_SOURCE_ERROR", label="Review the source error", detail="Read the quarantined or invalid-source reason before proceeding."),
        RecommendedAction(code="CORRECT_SOURCE", label="Correct the source", detail="Provide a corrected source through the normal ingestion workflow."),
        RecommendedAction(code="RERUN_RECONCILIATION", label="Rerun reconciliation", detail="Rerun only after the corrected source is accepted."),
    ),
    "ORDER_EXCESS": (
        RecommendedAction(code="CHECK_ORDER_PAYMENTS", label="Check order payments", detail="Review all payments allocated to the order and the exact excess amount."),
        RecommendedAction(code="TRACE_PAYMENT_PROOF", label="Trace payment proof", detail="Open the order proof and verify its payment evidence."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="Record the operator's disposition. The review becomes complete and does not change the proof."),
    ),
    "OPEN_REVIEW": (
        RecommendedAction(code="OPEN_REVIEW_ITEM", label="Open the review item", detail="Review the persisted exception and its proof before deciding."),
        RecommendedAction(code="TRACE_SOURCE_LINEAGE", label="Trace source lineage", detail="Use the proof sources to verify the evidence chain."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="Record a reasoned human decision; the assistant cannot approve it."),
    ),
    "PAISE_RUPEE_MISMATCH": (
        RecommendedAction(code="CHECK_CURRENCY_UNIT", label="Check the currency unit", detail="Confirm that the source amount is recorded in the configured integer-paise unit."),
        RecommendedAction(code="TRACE_SOURCE_LINEAGE", label="Trace source lineage", detail="Open the proof sources and verify the original amount fields."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="If the unit conversion cannot be explained, record an unresolved disposition. This marks the review complete and does not change the proof."),
    ),
    "MANUAL_BANK_MATCH_REQUIRED": (
        RecommendedAction(code="COMPARE_CANDIDATES", label="Compare the candidates", detail="Review the bank candidates and select one only when the evidence is unique."),
        RecommendedAction(code="CONFIRM_UTR", label="Confirm the UTR", detail="Use the bank reference and amount to confirm the candidate."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="Record a human decision when the evidence remains ambiguous."),
    ),
    "UNEXPECTED_MULTIPLE_SETTLED_PAYMENTS": (
        RecommendedAction(code="CHECK_ORDER_PAYMENTS", label="Check order payments", detail="Review all settled payments allocated to the order."),
        RecommendedAction(code="TRACE_PAYMENT_PROOF", label="Trace payment proof", detail="Open the order proof and verify each payment source."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="Record the operator's disposition. The review becomes complete and does not change the proof."),
    ),
    "NON_PROCESSABLE_SETTLEMENT_STATUS": (
        RecommendedAction(code="CHECK_SETTLEMENT_STATUS", label="Check settlement status", detail="Confirm the source status and whether this settlement can be processed."),
        RecommendedAction(code="TRACE_SOURCE_LINEAGE", label="Trace source lineage", detail="Verify the status in the immutable source snapshot."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="Record a human decision when the status cannot be processed automatically."),
    ),
    "PENDING": (
        RecommendedAction(code="CHECK_POSTING_WINDOW", label="Check posting timing", detail="Confirm whether the bank credit is still inside the configured timing window."),
        RecommendedAction(code="WAIT_FOR_POSTING", label="Wait for posting", detail="A pending item may need a later bank posting before it can be resolved."),
        RecommendedAction(code="RECORD_HUMAN_REVIEW", label="Record human review", detail="Record an operator decision only with supporting evidence."),
    ),
}


def guidance_for(canonical: dict[str, object]) -> tuple[RecommendedAction, ...]:
    """Return a fixed playbook chosen only from verified canonical facts."""
    if canonical.get("decision", canonical.get("status")) == "AUTO_VERIFIED":
        return ()
    if "total_close_blockers" in canonical:
        if canonical["total_close_blockers"] == 0:
            return ()
        return (
            RecommendedAction(code="CHECK_CLOSE_POLICY", label="Start with non-reviewable blockers", detail="Check integrity and system-error blockers before ordinary exceptions. An operator review cannot clear a proof integrity failure."),
            RecommendedAction(code="REVIEW_EXCEPTION_EVIDENCE", label="Work through the review queue", detail="Open each exception, compare its proof with the source evidence and record a reasoned disposition. Financial matching and review completion are separate."),
        )
    if not canonical:
        return (
            RecommendedAction(code="SELECT_EVIDENCE", label="Select an exception", detail="Select a settlement or exception so ProofClose can read its current evidence."),
        )
    keys: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"exception_type", "decision", "status"} and isinstance(item, str):
                    keys.append(item)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(canonical)
    for key in keys:
        if key in _PLAYBOOKS:
            return _PLAYBOOKS[key]
    return _PLAYBOOKS["OPEN_REVIEW"]
