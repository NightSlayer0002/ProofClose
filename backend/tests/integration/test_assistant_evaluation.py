import json

from evals.assistant_runner import run_assistant_evaluation
from evals.fixtures import assistant_fixtures_path


def test_offline_assistant_evaluation_is_grounded_and_provider_latency_unavailable() -> None:
    fixtures = json.loads(assistant_fixtures_path().read_text(encoding="utf-8"))
    result = run_assistant_evaluation(None, fixtures, live=False, max_provider_calls=0)
    assert result["manifest"]["mode"] == "offline"
    assert result["manifest"]["provider_calls"]["successful"] == 0
    assert result["metrics"]["unsupported_claim_count"] == 0
    assert result["metrics"]["provider_latency_p50_ms"] == "unavailable"
    assert result["metrics"]["provider_latency_p95_ms"] == "unavailable"
    assert result["metrics"]["tool_selection_accuracy"] == 1.0
    assert result["metrics"]["grounded_answer_accuracy"] == 1.0
    assert result["metrics"]["guidance_action_suitability"] == 1.0
    assert result["metrics"]["false_refusal_rate"] == 0.0
    assert result["metrics"]["adversarial_refusal_rate"] == 1.0
    assert result["manifest"]["provider_retries"] == 0
    assert {case["actual_mode"] for case in result["cases"]} == {
        "GENERAL_HELP", "CURRENT_FACT", "EVIDENCE_GUIDANCE", "UNABLE_TO_VERIFY"
    }


def test_assistant_evaluation_does_not_accept_mutated_required_fact() -> None:
    fixtures = json.loads(assistant_fixtures_path().read_text(encoding="utf-8"))
    fixture = fixtures[0]
    fixture["required_facts"] = {"state": "NOT_THE_RUNTIME_STATE"}
    result = run_assistant_evaluation(None, [fixture], live=False, max_provider_calls=0)
    assert result["metrics"]["grounded_answer_accuracy"] == 0.0
