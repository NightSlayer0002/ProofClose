from __future__ import annotations

from collections import Counter
from typing import Any


RATIO_METRICS = {
    "auto_match_precision": ("auto_match_true_positive", "auto_match_predictions"),
    "automation_rate_by_settlement_count": ("automated_settlements", "settlement_count"),
    "money_automation_rate": ("automated_paise", "expected_paise"),
    "exception_precision": ("exception_true_positive", "exception_predictions"),
    "exception_recall": ("exception_true_positive", "exception_truth"),
    "ambiguous_abstention_recall": ("ambiguous_abstentions", "ambiguous_truth"),
    "proof_coverage": ("proof_covered_subjects", "proof_required_subjects"),
    "proof_subject_accuracy": ("proof_subject_correct", "proof_subject_checked"),
    "historical_reproduction_success_rate": ("historical_reproduced", "historical_available"),
    "tamper_detection_rate": ("tamper_detected", "tamper_probes"),
}


def safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _exception_key(item: dict[str, Any], row_by_proof: dict[str, dict[str, Any]]) -> tuple[str, str, str] | None:
    subject_type = item.get("subject_type")
    subject_id = item.get("subject_id")
    if not subject_type or not subject_id:
        row = row_by_proof.get(str(item.get("proof_id", "")))
        if row is not None:
            subject_type = "SETTLEMENT"
            subject_id = row["settlement_id"]
    exception_type = item.get("exception_type")
    if not all(isinstance(value, str) and value for value in (subject_type, subject_id, exception_type)):
        return None
    return str(subject_type), str(subject_id), str(exception_type)


def calculate_metric_counts(
    rows: list[dict],
    exceptions: list[dict],
    match_truth: dict,
    exception_truth: dict,
    run: dict,
    *,
    proof_checks: dict[str, int] | None = None,
) -> dict[str, int]:
    """Produce additive counts so multi-seed ratios are rounded only once."""
    automatic_truth = set(match_truth.get("automatic_matches", ()))
    automatic_predictions = {row["settlement_id"] for row in rows if row["decision"] == "AUTO_VERIFIED"}
    ambiguous_truth = set(match_truth.get("ambiguous_settlements", ()))
    refused = {row["settlement_id"] for row in rows if row["decision"] == "REFUSED"}
    row_by_proof = {row["proof_id"]: row for row in rows if row.get("proof_id")}
    predicted_exceptions = {
        key for item in exceptions if (key := _exception_key(item, row_by_proof)) is not None
    }
    expected_exceptions = {
        (item["subject_type"], item["subject_id"], item["exception_type"])
        for item in exception_truth.get("exceptions", ())
    }

    automated_rows = [row for row in rows if row["decision"] == "AUTO_VERIFIED"]
    expected_paise = sum(int(row.get("expected_paise", 0)) for row in rows)
    automated_paise = sum(int(row.get("expected_paise", 0)) for row in automated_rows)
    automatic_bank_refs = [str(row["bank_ref"]) for row in automated_rows if row.get("bank_ref")]
    duplicate_allocations = sum(count - 1 for count in Counter(automatic_bank_refs).values() if count > 1)
    invalid_candidate_counts = sum(
        row.get("evidence", {}).get("candidate_count") != 1 or not row.get("bank_ref")
        for row in automated_rows
    )

    checks = {
        "proof_covered_subjects": len(row_by_proof),
        "proof_required_subjects": len(rows),
        "proof_subject_correct": 0,
        "proof_subject_checked": 0,
        "historical_reproduced": 0,
        "historical_available": 0,
        "tamper_detected": 0,
        "tamper_probes": 0,
    }
    checks.update(proof_checks or {})
    return {
        "auto_match_true_positive": len(automatic_predictions & automatic_truth),
        "auto_match_predictions": len(automatic_predictions),
        "automated_settlements": len(automated_rows),
        "settlement_count": len(rows),
        "automated_paise": automated_paise,
        "expected_paise": expected_paise or int(run.get("expected_paise", 0)),
        "exception_true_positive": len(predicted_exceptions & expected_exceptions),
        "exception_predictions": len(predicted_exceptions),
        "exception_truth": len(expected_exceptions),
        "ambiguous_abstentions": len(refused & ambiguous_truth),
        "ambiguous_truth": len(ambiguous_truth),
        "false_refusal_count": len(refused - set(match_truth.get("refused_settlements", ambiguous_truth))),
        "unique_allocation_violation_count": duplicate_allocations + invalid_candidate_counts,
        **checks,
    }


def metrics_from_counts(counts: dict[str, int]) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {
        name: safe_ratio(counts[numerator], counts[denominator])
        for name, (numerator, denominator) in RATIO_METRICS.items()
    }
    precision = float(metrics["exception_precision"])
    recall = float(metrics["exception_recall"])
    metrics["exception_f1"] = round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0
    metrics["false_refusal_count"] = counts["false_refusal_count"]
    metrics["unique_allocation_violation_count"] = counts["unique_allocation_violation_count"]
    return metrics


def calculate_metrics(
    rows: list[dict],
    exceptions: list[dict],
    match_truth: dict,
    exception_truth: dict,
    run: dict,
    *,
    proof_checks: dict[str, int] | None = None,
) -> dict[str, int | float]:
    return metrics_from_counts(
        calculate_metric_counts(rows, exceptions, match_truth, exception_truth, run, proof_checks=proof_checks)
    )


def sum_metric_counts(items: list[dict[str, int]]) -> dict[str, int]:
    keys = set().union(*(item.keys() for item in items)) if items else set()
    return {key: sum(item.get(key, 0) for item in items) for key in keys}
