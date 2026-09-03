from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

from app.config import Settings
from app.domain.models import ProofObject
from app.main import create_app
from app.proofs.fingerprint import ProofIntegrityError, verify_artifact_fingerprint
from app.reconciliation.rules import (
    CONFIGURATION_VERSION,
    ORDER_RULE_NAME,
    ORDER_RULE_VERSION_V1,
    RULE_VERSION,
    SETTLEMENT_RULE_NAME,
)
from evals.generator import build_demo_files, scenario_manifest
from evals.metrics import calculate_metric_counts, metrics_from_counts, sum_metric_counts


FIXTURES = Path(__file__).parent / "fixtures"
PROOF_SCHEMA_VERSION = "proof-object/v2"
CLOSE_PACK_SCHEMA_VERSION = "proofclose-close-pack/v2"


def git_commit() -> str:
    root = Path.cwd().resolve()
    command = ["git", "-c", f"safe.directory={root.as_posix()}", "rev-parse", "HEAD"]
    try:
        return subprocess.run(command, cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _load_truth_templates() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        json.loads((FIXTURES / "match_ground_truth.json").read_text(encoding="utf-8")),
        json.loads((FIXTURES / "exception_ground_truth.json").read_text(encoding="utf-8")),
    )


def _materialize_truth(seed: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    match_template, exception_template = _load_truth_templates()
    assignment = scenario_manifest(seed)
    by_scenario: dict[str, list[str]] = {}
    for item in assignment["settlements"]:
        by_scenario.setdefault(item["scenario"], []).append(item["settlement_id"])
    automatic = {
        settlement_id
        for scenario in match_template["automatic_scenarios"]
        for settlement_id in by_scenario.get(scenario, ())
    }
    ambiguous = {
        settlement_id
        for scenario in match_template["ambiguous_scenarios"]
        for settlement_id in by_scenario.get(scenario, ())
    }
    refused = {
        settlement_id
        for scenario in match_template["refused_scenarios"]
        for settlement_id in by_scenario.get(scenario, ())
    }
    exceptions = [
        {
            "subject_type": "SETTLEMENT",
            "subject_id": settlement_id,
            "exception_type": exception_type,
        }
        for scenario, exception_type in exception_template["settlement_exception_by_scenario"].items()
        for settlement_id in by_scenario.get(scenario, ())
    ]
    exceptions.extend(exception_template["fixed_subject_exceptions"])
    return (
        {
            "dataset_version": match_template["dataset_version"],
            "automatic_matches": sorted(automatic),
            "ambiguous_settlements": sorted(ambiguous),
            "refused_settlements": sorted(refused),
        },
        {"dataset_version": exception_template["dataset_version"], "exceptions": exceptions},
        assignment,
    )


def _proof_and_integrity_checks(app: Any, tenant_id: str, run_id: str, rows: list[dict], exception_truth: dict) -> tuple[dict[str, int], dict[str, Any], dict[str, Any]]:
    proofs = app.state.proof_service.list_for_run(tenant_id, run_id)
    required_subjects = {("SETTLEMENT", row["settlement_id"]) for row in rows}
    required_subjects.update(
        (item["subject_type"], item["subject_id"]) for item in exception_truth["exceptions"]
    )
    proof_subjects = {
        (proof.subject.subject_type.value, proof.subject.subject_id)
        for proof in proofs
    }

    reproduction_results = [
        app.state.proof_service.reproduce(proof.proof_id, tenant_id=tenant_id)
        for proof in proofs
    ]
    available_reproductions = len(reproduction_results)
    reproduced = sum(result.status == "REPRODUCED" for result in reproduction_results)

    unavailable_probe = {"status": "unavailable", "failure_type": None}
    if proofs:
        probe_proof = proofs[0]
        evaluator = app.state.proof_service.registry.resolve(probe_proof.rule_name, probe_proof.rule_version)
        if evaluator is not None:
            app.state.proof_service.registry.remove(probe_proof.rule_name, probe_proof.rule_version)
            try:
                result = app.state.proof_service.reproduce(probe_proof.proof_id, tenant_id=tenant_id)
                unavailable_probe = {
                    "status": result.status,
                    "failure_type": result.failure_type,
                }
            finally:
                app.state.proof_service.registry.register(probe_proof.rule_name, probe_proof.rule_version, evaluator)

    tamper_detected = 0
    if proofs and isinstance(proofs[0], ProofObject):
        payload = proofs[0].model_dump(mode="python")
        payload["tenant_id"] = "tampered-tenant"
        try:
            verify_artifact_fingerprint(payload)
        except ProofIntegrityError:
            tamper_detected = 1

    checks = {
        "proof_covered_subjects": len(proof_subjects & required_subjects),
        "proof_required_subjects": len(required_subjects),
        "proof_subject_correct": sum(
            (proof.subject.subject_type.value, proof.subject.subject_id) in required_subjects
            for proof in proofs
        ),
        "proof_subject_checked": len(proofs),
        "historical_reproduced": reproduced,
        "historical_available": available_reproductions,
        "tamper_detected": tamper_detected,
        "tamper_probes": 1 if proofs else 0,
    }
    reproduction = {
        "available_attempts": available_reproductions,
        "reproduced": reproduced,
        "unavailable_version_probe": unavailable_probe,
    }
    tamper = {"probes": 1 if proofs else 0, "detected": tamper_detected}
    return checks, reproduction, tamper


def _annotate_exceptions(app: Any, tenant_id: str, run_id: str, exceptions: list[dict]) -> list[dict]:
    annotated: list[dict] = []
    for item in exceptions:
        proof = app.state.proof_service.get(item["proof_id"], tenant_id)
        if proof.run_id != run_id:
            raise RuntimeError("evaluation proof escaped the current run")
        annotated.append(
            {
                **item,
                "subject_type": proof.subject.subject_type.value,
                "subject_id": proof.subject.subject_id,
            }
        )
    return annotated


def _manifest(seed: int, dataset_version: str, record_count: int) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "dataset_seed": seed,
        "dataset_version": dataset_version,
        "rule_version": RULE_VERSION,
        "rule_versions": {
            SETTLEMENT_RULE_NAME: RULE_VERSION,
            ORDER_RULE_NAME: ORDER_RULE_VERSION_V1,
        },
        "configuration_version": CONFIGURATION_VERSION,
        "proof_schema_version": PROOF_SCHEMA_VERSION,
        "close_pack_schema_version": CLOSE_PACK_SCHEMA_VERSION,
        "evaluation_mode": "deterministic_offline",
        "model_provider": None,
        "model_name": None,
        "prompt_version": None,
        "embedding_model_version": None,
        "records_processed": record_count,
    }


def _write_report(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation_results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    with (output_dir / "evaluation_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerows(report["metrics"].items())
    (output_dir / "eval_manifest.json").write_text(
        json.dumps(report["manifest"], indent=2, sort_keys=True), encoding="utf-8"
    )


def run_evaluation(seed: int, output_dir: Path, *, write_artifacts: bool = True) -> dict[str, Any]:
    match_truth, exception_truth, assignment = _materialize_truth(seed)
    with TemporaryDirectory(prefix="proofclose-eval-") as temporary:
        app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=Path(temporary)))
        try:
            tenant_id = app.state.settings.demo_tenant_id
            source_ids: list[str] = []
            record_count = 0
            for source_type, (filename, content) in build_demo_files(seed).items():
                result = app.state.ingestion.ingest_csv(tenant_id, source_type, filename, content)
                if result.state != "ACCEPTED":
                    raise RuntimeError(f"evaluation source rejected: {source_type}: {result.error}")
                source_ids.append(result.source_id)
                record_count += result.accepted_rows
            snapshot = app.state.snapshots.create(tenant_id, source_ids)
            run = app.state.run_service.run_snapshot(tenant_id, snapshot.snapshot_id)
            rows = app.state.run_service.list_results(tenant_id, run["run_id"])
            raw_exceptions = app.state.review_service.list_exceptions(tenant_id, run["run_id"])
            exceptions = _annotate_exceptions(app, tenant_id, run["run_id"], raw_exceptions)
            proof_checks, reproduction, tamper = _proof_and_integrity_checks(
                app, tenant_id, run["run_id"], rows, exception_truth
            )
            counts = calculate_metric_counts(
                rows, exceptions, match_truth, exception_truth, run, proof_checks=proof_checks
            )
        finally:
            app.state.database.dispose()
            app.state.observability.dispose()

    report = {
        "manifest": _manifest(seed, match_truth["dataset_version"], record_count),
        "metrics": metrics_from_counts(counts),
        "metric_counts": counts,
        "scenario_assignment": assignment,
        "run": run,
        "predictions": rows,
        "detected_exceptions": exceptions,
        "proof_reproduction": reproduction,
        "tamper_probe": tamper,
    }
    if write_artifacts:
        _write_report(output_dir, report)
    return report


def run_evaluations(seeds: list[int], output_dir: Path) -> dict[str, Any]:
    if not seeds:
        raise ValueError("at least one evaluation seed is required")
    reports = [run_evaluation(seed, output_dir, write_artifacts=False) for seed in seeds]
    counts = sum_metric_counts([report["metric_counts"] for report in reports])
    manifest = {
        **reports[0]["manifest"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_seed": None,
        "dataset_seeds": seeds,
        "records_processed": sum(report["manifest"]["records_processed"] for report in reports),
        "seed_count": len(seeds),
    }
    report = {
        "manifest": manifest,
        "metrics": metrics_from_counts(counts),
        "metric_counts": counts,
        "seed_reports": reports,
    }
    _write_report(output_dir, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the deterministic ProofClose system evaluation")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seed", type=int)
    group.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--output", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    selected = args.seeds or ([args.seed] if args.seed is not None else [20260831])
    result = run_evaluations(selected, args.output) if len(selected) > 1 else run_evaluation(selected[0], args.output)
    print(json.dumps(result["metrics"], indent=2, sort_keys=True))
