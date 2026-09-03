import json
from pathlib import Path

from evals.metrics import calculate_metrics
from evals.metrics import metrics_from_counts, sum_metric_counts
from evals.runner import scenario_manifest

from evals.runner import run_evaluation


def test_evaluation_calculates_metrics_and_reproducibility_artifacts(tmp_path) -> None:
    """Benchmark claims must come from the held-out labels and recorded run output."""
    report = run_evaluation(seed=20260831, output_dir=tmp_path)
    assert report["metrics"]["auto_match_precision"] == 1.0
    assert report["metrics"]["ambiguous_abstention_recall"] == 1.0
    assert report["metrics"]["exception_precision"] == 1.0
    assert report["metrics"]["exception_recall"] == 1.0
    assert report["metrics"]["exception_f1"] == 1.0
    assert report["metrics"]["false_refusal_count"] == 0
    assert report["metrics"]["unique_allocation_violation_count"] == 0
    assert report["metrics"]["proof_coverage"] == 1.0
    assert report["metrics"]["proof_subject_accuracy"] == 1.0
    assert report["metrics"]["historical_reproduction_success_rate"] == 1.0
    assert report["metrics"]["tamper_detection_rate"] == 1.0
    assert "match_coverage" not in report["metrics"]
    assert "percentage_money_explained" not in report["metrics"]
    for name in ("evaluation_results.json", "evaluation_results.csv", "eval_manifest.json"):
        assert (tmp_path / name).is_file()
    manifest = json.loads((tmp_path / "eval_manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_seed"] == 20260831
    assert manifest["rule_version"] == "2.0"
    assert manifest["configuration_version"] == "2.0"
    assert manifest["proof_schema_version"] == "proof-object/v2"
    assert manifest["close_pack_schema_version"] == "proofclose-close-pack/v2"


def test_scenario_manifest_is_deterministic_and_seed_changes_assignment() -> None:
    first = scenario_manifest(20260831)
    assert first == scenario_manifest(20260831)
    assert first != scenario_manifest(20260901)
    assert {item["scenario"] for item in first["settlements"]} >= {
        "unique_exact_match", "duplicate_bank_candidates", "pending", "order_excess"
    }
    assert set(first["boundary_scenarios"]) == {
        "shared_bank_row",
        "utr_mismatch",
        "amount_mismatch",
        "time_mismatch",
        "single_amount_only_candidate",
        "multiple_amount_only_candidates",
        "future_timestamp",
        "non_processable_status",
        "currency_mismatch",
        "proof_mutation",
        "unavailable_v1_rule",
    }
    assignments = {
        seed: next(
            item["settlement_id"]
            for item in scenario_manifest(seed)["settlements"]
            if item["scenario"] == "duplicate_bank_candidates"
        )
        for seed in (20260831, 20260901, 20260902)
    }
    assert len(set(assignments.values())) > 1


def test_finance_metrics_use_truth_and_change_when_predictions_mutate() -> None:
    rows = [{"settlement_id": "s1", "decision": "AUTO_VERIFIED", "expected_paise": 100, "proof_id": "p1"}]
    exceptions = [{"proof_id": "p1", "exception_type": "X", "subject_type": "SETTLEMENT", "subject_id": "s1"}]
    truth = {"automatic_matches": ["s1"], "ambiguous_settlements": []}
    exception_truth = {"exceptions": [{"subject_type": "SETTLEMENT", "subject_id": "s1", "exception_type": "X"}], "proof_subjects": []}
    run = {"expected_paise": 100, "explained_paise": 100}
    good = calculate_metrics(rows, exceptions, truth, exception_truth, run)
    rows[0]["decision"] = "REVIEW_REQUIRED"
    bad = calculate_metrics(rows, exceptions, truth, exception_truth, run)
    assert good["auto_match_precision"] == 1.0
    assert bad["auto_match_precision"] == 0.0
    assert good["exception_f1"] == 1.0


def test_multi_seed_ratios_are_computed_from_summed_counts_before_rounding() -> None:
    combined = sum_metric_counts(
        [
            {
                "auto_match_true_positive": 1, "auto_match_predictions": 3,
                "automated_settlements": 1, "settlement_count": 3,
                "automated_paise": 1, "expected_paise": 3,
                "exception_true_positive": 1, "exception_predictions": 3, "exception_truth": 3,
                "ambiguous_abstentions": 1, "ambiguous_truth": 3,
                "proof_covered_subjects": 1, "proof_required_subjects": 3,
                "proof_subject_correct": 1, "proof_subject_checked": 3,
                "historical_reproduced": 1, "historical_available": 3,
                "tamper_detected": 1, "tamper_probes": 3,
                "false_refusal_count": 0, "unique_allocation_violation_count": 0,
            },
            {
                "auto_match_true_positive": 2, "auto_match_predictions": 3,
                "automated_settlements": 2, "settlement_count": 3,
                "automated_paise": 2, "expected_paise": 3,
                "exception_true_positive": 2, "exception_predictions": 3, "exception_truth": 3,
                "ambiguous_abstentions": 2, "ambiguous_truth": 3,
                "proof_covered_subjects": 2, "proof_required_subjects": 3,
                "proof_subject_correct": 2, "proof_subject_checked": 3,
                "historical_reproduced": 2, "historical_available": 3,
                "tamper_detected": 2, "tamper_probes": 3,
                "false_refusal_count": 0, "unique_allocation_violation_count": 0,
            },
        ]
    )
    assert metrics_from_counts(combined)["auto_match_precision"] == 0.5


def test_application_runtime_does_not_import_evaluation_ground_truth() -> None:
    application_root = Path("backend/app")
    source = "\n".join(path.read_text(encoding="utf-8") for path in application_root.rglob("*.py"))
    assert "match_ground_truth" not in source
    assert "exception_ground_truth" not in source
