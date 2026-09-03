from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.investigations.contracts import AssistantContext, ProviderResult, ProviderStatus, ToolSelection
from app.investigations.provider import ProviderFailure
from app.main import create_app


def initialized_client(tmp_path: Path, pending_hours: int = 3) -> TestClient:
    app = create_app(
        Settings(
            PROOFCLOSE_ENV="demo",
            PROOFCLOSE_DATA_DIR=tmp_path,
            PROOFCLOSE_BANK_PENDING_HOURS=pending_hours,
            NVIDIA_API_KEY=None,
        )
    )
    client = TestClient(app)
    client.__enter__()
    client.post("/api/demo/seed")
    run = client.post("/api/runs", json={}).json()
    client.run_id = run["run_id"]
    return client


def test_direct_investigation_works_without_model_credentials(tmp_path) -> None:
    """A missing model must not block deterministic finance questions."""
    client = initialized_client(tmp_path)
    try:
        response = client.post(
            "/api/investigations/query",
            json={"run_id": client.run_id, "question": "What prevents today's close?"},
        )
        report = response.json()
        assert report["route"] == "DIRECT_TOOL"
        assert report["unresolved_paise"] > 0
        assert report["unsupported_factual_claims"] == 0
        assert report["proof_ids"]
        assert report["citations"]["support_scope"] == "AGGREGATE"
        assert report["supporting_record_count"] == len(report["proof_ids"])
        assert report["run_record_count"] > report["supporting_record_count"]
        assert {line["classification"] for line in report["lines"]} <= {"OBSERVED", "CALCULATED", "UNRESOLVED"}
    finally:
        client.__exit__(None, None, None)


def test_unsupported_question_refuses_honestly_when_ai_is_unavailable(tmp_path) -> None:
    """The application must not fabricate a complex answer during model outage."""
    client = initialized_client(tmp_path)
    try:
        response = client.post(
            "/api/investigations/query",
            json={"run_id": client.run_id, "question": "Forecast next quarter's card mix."},
        )
        assert response.status_code == 200
        report = response.json()
        assert report["route"] == "REFUSE"
        assert report["status"] == "REFUSED"
        assert report["provider"]["configuration_status"] == "not_configured"
        assert report["provider"]["reachability_status"] == "not_probed"
        assert report["narration"] is None
        assert report["estimated_cost"] == "unavailable"
        assert report["unresolved_paise"] is None
    finally:
        client.__exit__(None, None, None)


def test_question_contract_rejects_blank_control_and_overlong_input(tmp_path) -> None:
    client = initialized_client(tmp_path)
    try:
        for question in ("   ", "\x00\x01\n", "x" * 1001):
            response = client.post(
                "/api/investigations/query",
                json={"run_id": client.run_id, "question": question},
            )
            assert response.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_exception_review_is_audited_and_does_not_delete_original(tmp_path) -> None:
    """A manual resolution must preserve the original proof and previous state."""
    client = initialized_client(tmp_path)
    try:
        exception = client.get(f"/api/exceptions?run_id={client.run_id}").json()["items"][0]
        response = client.post(
            f"/api/exceptions/{exception['exception_id']}/review",
            json={"action": "LEAVE_UNRESOLVED", "reason": "Bank confirmation requested"},
        )
        reviewed = response.json()
        assert reviewed["previous_state"] == "OPEN"
        assert reviewed["new_state"] == "LEFT_UNRESOLVED"
        audit = client.get(f"/api/audit?run_id={client.run_id}").json()["items"]
        assert audit[-1]["reason"] == "Bank confirmation requested"
        proof = client.get(f"/api/proofs/{exception['proof_id']}")
        assert proof.status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_close_requires_review_then_explicit_approval_with_exceptions(tmp_path) -> None:
    """The locked v2 configuration keeps a still-pending settlement blocked."""
    client = initialized_client(tmp_path, pending_hours=1)
    try:
        close = client.get(f"/api/close?run_id={client.run_id}").json()
        assert close["state"] == "BLOCKED"
        exceptions = client.get(f"/api/exceptions?run_id={client.run_id}").json()["items"]
        for item in exceptions:
            client.post(
                f"/api/exceptions/{item['exception_id']}/review",
                json={"action": "LEAVE_UNRESOLVED", "reason": "Escalated to bank operations"},
            )
        reviewed = client.get(f"/api/close?run_id={client.run_id}").json()
        assert reviewed["state"] == "BLOCKED"
        approval = client.post(
            "/api/close/approve",
            json={"run_id": client.run_id, "reason": "Controller accepts documented exceptions"},
        )
        assert approval.status_code == 409
    finally:
        client.__exit__(None, None, None)


def test_reviewed_exceptions_do_not_hide_unreviewable_pending_money(tmp_path) -> None:
    """A pending result without a reviewed exception must keep close blocked."""
    client = initialized_client(tmp_path)
    try:
        exceptions = client.get(f"/api/exceptions?run_id={client.run_id}").json()["items"]
        for item in exceptions:
            client.post(
                f"/api/exceptions/{item['exception_id']}/review",
                json={"action": "LEAVE_UNRESOLVED", "reason": "Escalated to bank operations"},
            )
        close = client.get(f"/api/close?run_id={client.run_id}").json()
        assert close["unresolved_paise"] > 0
        assert close["state"] == "BLOCKED"
        assert close["unreviewable_blockers"] == 1
    finally:
        client.__exit__(None, None, None)


def test_proof_routes_keep_reproduction_and_reevaluation_separate(tmp_path) -> None:
    """The API must not let a current-rule comparison masquerade as reproduction."""
    client = initialized_client(tmp_path)
    try:
        row = client.get(f"/api/runs/{client.run_id}/settlements").json()["items"][0]
        proof_id = row["proof_id"]
        reproduced = client.post(f"/api/proofs/{proof_id}/reproduce").json()
        reevaluated = client.post(f"/api/proofs/{proof_id}/reevaluate").json()
        assert reproduced["operation"] == "HISTORICAL_REPRODUCTION"
        assert reproduced["status"] == "REPRODUCED"
        assert reevaluated["operation"] == "CURRENT_RULE_REEVALUATION"
        assert reevaluated["proof"]["supersedes_proof_id"] == proof_id
    finally:
        client.__exit__(None, None, None)


class _ScopeAttackingProvider:
    def __init__(self, selection: ToolSelection) -> None:
        self.selection = selection
        self.calls = 0

    def status(self) -> ProviderStatus:
        return ProviderStatus(configuration_status="configured", reachability_status="reachable", model="test")

    def plan(self, _question, _context: AssistantContext, _allowed_tools, *, attempt_guard):
        if not attempt_guard():
            raise ProviderFailure("provider_budget_exhausted")
        self.calls += 1
        return self.selection, ProviderResult(content="{}", model="test")

    def narrate(self, _question, _tool_name, _canonical, *, attempt_guard):
        if not attempt_guard():
            raise ProviderFailure("provider_budget_exhausted")
        return ProviderResult(content='{"fact_keys":["state"]}', model="test")


def test_service_rescopes_planner_run_before_finance_tool_execution(tmp_path) -> None:
    provider = _ScopeAttackingProvider(
        ToolSelection(name="close_summary", arguments={"run_id": "attacker-run"}, route="PLANNER_TOOL")
    )
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path), assistant_provider=provider)
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        answer = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "What is the most important settlement issue in this run?"},
        ).json()
    assert answer["route"] == "PLANNER_TOOL"
    assert answer["canonical"]["run_id"] == run["run_id"]


def test_service_rejects_planner_extra_tenant_argument_before_finance_tools(tmp_path) -> None:
    provider = _ScopeAttackingProvider(
        ToolSelection(
            name="close_summary",
            arguments={"run_id": "attacker-run", "tenant_id": "other-tenant"},
            route="PLANNER_TOOL",
        )
    )
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path), assistant_provider=provider)
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        response = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "What is the most important settlement issue in this run?"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "REFUSED"
    assert response.json()["narration_status"] == "provider_unavailable"
