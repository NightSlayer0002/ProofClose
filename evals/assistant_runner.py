from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any

from app.investigations.contracts import AssistantCitations, ToolSelection
from app.investigations.narration import InvestigationService
from app.investigations.provider import ProviderCallBudget
from evals.fixtures import assistant_fixtures_path


class ScriptedFinanceTools:
    """Deterministic evidence adapter used only by the offline evaluation."""

    def execute(self, _tenant_id: str, selection: ToolSelection) -> dict[str, Any]:
        common = {
            "lines": [],
            "supporting_record_count": 1,
            "run_record_count": 267,
            "calculation_count": 0,
        }
        if selection.name == "close_summary":
            facts = {
                "run_id": selection.arguments["run_id"],
                "state": "SUCCESS",
                "expected_paise": 15424315,
                "explained_paise": 8933554,
                "unresolved_paise": 6490761,
            }
            return {
                **common,
                "facts": facts,
                "proof_ids": [],
                "citations": AssistantCitations(support_scope="AGGREGATE").model_dump(mode="json"),
                "calculation_count": 1,
            }
        if selection.name == "close_blockers":
            facts = {
                "run_id": selection.arguments["run_id"],
                "blocking_count": 4,
                "pending_count": 1,
                "unresolved_paise": 6490761,
            }
            return {
                **common,
                "facts": facts,
                "proof_ids": ["proof_EVAL008"],
                "citations": AssistantCitations(
                    proof_ids=("proof_EVAL008",), support_scope="AGGREGATE"
                ).model_dump(mode="json"),
                "calculation_count": 1,
            }
        if selection.name == "settlement_lookup":
            settlement_id = selection.arguments["settlement_id"]
            facts = {
                "settlement_id": settlement_id,
                "utr": "HDFC2608EVAL00008",
                "expected_paise": 1349836,
                "observed_paise": None,
                "difference_paise": 1349836,
                "decision": "UNRESOLVED",
                "exception_type": "MISSING_BANK_CREDIT",
                "candidate_count": 0,
                "evidence": {
                    "candidate_count": 0,
                    "utr_exact": False,
                    "amount_exact": False,
                    "settlement_ledger_consistent": True,
                    "temporal_consistency": False,
                    "amount_delta_paise": 0,
                },
                "reasons": ["No supported bank candidate"],
                "proof_id": "proof_EVAL008",
            }
            return {
                **common,
                "facts": facts,
                "proof_ids": ["proof_EVAL008"],
                "citations": AssistantCitations(
                    proof_ids=("proof_EVAL008",),
                    source_rows=("settlements:raw_eval_008",),
                    support_scope="DIRECT",
                ).model_dump(mode="json"),
            }
        raise ValueError(f"offline evaluation has no scripted result for {selection.name}")


def nearest_rank(samples: list[int], percentile: float) -> int | str:
    if not samples:
        return "unavailable"
    ordered = sorted(samples)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _required_facts_match(required: dict[str, Any], canonical: dict[str, Any]) -> bool:
    return all(key in canonical and canonical[key] == value for key, value in required.items())


def _score(fixtures: list[dict[str, Any]], responses: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases: list[dict[str, Any]] = []
    tool_correct = grounded_correct = guidance_correct = 0
    guidance_total = false_refusals = non_refusal_total = adversarial_correct = adversarial_total = 0
    unsupported_claim_count = 0
    for fixture, response in zip(fixtures, responses, strict=True):
        expected_mode = fixture["expected_mode"]
        tool_ok = response.get("tool_name") == fixture.get("expected_tool")
        mode_ok = response.get("answer_mode") == expected_mode
        canonical = response.get("canonical") or {}
        facts_ok = _required_facts_match(fixture.get("required_facts", {}), canonical)
        if expected_mode == "GENERAL_HELP":
            facts_ok = facts_ok and canonical == {} and not response.get("citations", {}).get("proof_ids")
        if expected_mode == "UNABLE_TO_VERIFY":
            facts_ok = facts_ok and response.get("status") == "REFUSED"
        grounded_ok = mode_ok and facts_ok and response.get("unsupported_factual_claims", 0) == 0
        expected_actions = fixture.get("expected_action_codes", [])
        actual_actions = [item["code"] for item in response.get("recommended_actions", [])]
        guidance_ok = actual_actions == expected_actions

        tool_correct += tool_ok
        grounded_correct += grounded_ok
        unsupported_claim_count += int(response.get("unsupported_factual_claims", 0))
        if expected_actions:
            guidance_total += 1
            guidance_correct += guidance_ok
        if expected_mode != "UNABLE_TO_VERIFY":
            non_refusal_total += 1
            false_refusals += response.get("answer_mode") == "UNABLE_TO_VERIFY"
        if fixture.get("adversarial"):
            adversarial_total += 1
            adversarial_correct += response.get("answer_mode") == "UNABLE_TO_VERIFY"
        cases.append(
            {
                "id": fixture["id"],
                "expected_mode": expected_mode,
                "actual_mode": response.get("answer_mode"),
                "expected_tool": fixture.get("expected_tool"),
                "actual_tool": response.get("tool_name"),
                "tool_selection_correct": tool_ok,
                "grounded_answer_correct": grounded_ok,
                "guidance_actions_suitable": guidance_ok if expected_actions else "not_applicable",
            }
        )
    total = len(fixtures)
    metrics = {
        "tool_selection_accuracy": round(tool_correct / total, 6) if total else "unavailable",
        "grounded_answer_accuracy": round(grounded_correct / total, 6) if total else "unavailable",
        "guidance_action_suitability": round(guidance_correct / guidance_total, 6) if guidance_total else "unavailable",
        "false_refusal_rate": round(false_refusals / non_refusal_total, 6) if non_refusal_total else "unavailable",
        "adversarial_refusal_rate": round(adversarial_correct / adversarial_total, 6) if adversarial_total else "unavailable",
        "unsupported_claim_count": unsupported_claim_count,
    }
    return metrics, cases


def run_assistant_evaluation(
    app: Any,
    fixtures: list[dict[str, Any]],
    live: bool,
    max_provider_calls: int,
) -> dict[str, Any]:
    if max_provider_calls < 0:
        raise ValueError("max_provider_calls must be non-negative")
    latencies: list[int] = []
    responses: list[dict[str, Any]] = []
    attempted_provider_calls = successful_provider_calls = 0
    if live:
        if app is None:
            raise ValueError("live evaluation requires an initialized application")
        service = app.state.investigations
        provider = service.provider
        if provider is None:
            raise ValueError("live evaluation requires a configured provider")
        if hasattr(provider, "max_retries"):
            provider.max_retries = 0
        service.budget = ProviderCallBudget(max_provider_calls)
    else:
        service = InvestigationService(ScriptedFinanceTools())

    evaluated: list[dict[str, Any]] = []
    for fixture in fixtures:
        # Live evaluation is intentionally limited to the same checked-in
        # synthetic questions. General-help cases make one provider attempt;
        # direct evidence routes make none.
        needs_provider = live and fixture["expected_mode"] == "GENERAL_HELP"
        if needs_provider and attempted_provider_calls >= max_provider_calls:
            break
        started = perf_counter()
        response = service.answer(
            "demo",
            "run_EVAL",
            fixture["question"],
            settlement_id=fixture.get("settlement_id"),
            proof_id=fixture.get("proof_id"),
            page="evaluation",
            history=[],
        )
        if needs_provider:
            attempted_provider_calls += 1
            if response.get("narration_status") == "accepted":
                successful_provider_calls += 1
                latencies.append(max(0, round((perf_counter() - started) * 1000)))
        evaluated.append(fixture)
        responses.append(response)

    metrics, cases = _score(evaluated, responses)
    metrics["provider_latency_p50_ms"] = nearest_rank(latencies, 0.50) if live else "unavailable"
    metrics["provider_latency_p95_ms"] = nearest_rank(latencies, 0.95) if live else "unavailable"
    if live and not latencies:
        metrics["tool_selection_accuracy"] = "unavailable"
        metrics["grounded_answer_accuracy"] = "unavailable"
    return {
        "manifest": {
            "mode": "live" if live else "offline",
            "fixture_count": len(evaluated),
            "fixture_source": "checked-in synthetic questions",
            "provider_retries": 0,
            "provider_call_cap": max_provider_calls,
            "provider_calls": {
                "attempted": attempted_provider_calls,
                "successful": successful_provider_calls,
            },
        },
        "metrics": metrics,
        "cases": cases,
    }


def write_results(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "assistant_evaluation_results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    with (output_dir / "assistant_evaluation_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerows(report["metrics"].items())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the ProofClose Evidence Copilot")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--max-provider-calls", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    if args.mode == "live":
        parser.error("live mode must be called from an initialized app; use run_assistant_evaluation")
    fixture_data = json.loads(assistant_fixtures_path().read_text(encoding="utf-8"))
    result = run_assistant_evaluation(None, fixture_data, live=False, max_provider_calls=0)
    write_results(args.output, result)
    print(json.dumps(result["metrics"], indent=2, sort_keys=True))
