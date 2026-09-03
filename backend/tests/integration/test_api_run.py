from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.investigations.contracts import AssistantContext, ProviderResult, ProviderStatus, ToolSelection
from app.investigations.provider import NvidiaProvider, ProviderCallBudget, ProviderFailure
from app.main import create_app


def make_client(tmp_path: Path, environment: str = "demo") -> TestClient:
    settings = Settings(PROOFCLOSE_ENV=environment, PROOFCLOSE_DATA_DIR=tmp_path, NVIDIA_API_KEY=None)
    return TestClient(create_app(settings))


def upload_snapshot(
    client: TestClient,
    *,
    merchant_orders: bytes,
    razorpay_recon: bytes,
    settlements: bytes,
    bank_statement: bytes,
) -> str:
    source_ids: list[str] = []
    uploads = (
        ("merchant_orders", "merchant_orders.csv", merchant_orders),
        ("razorpay_recon", "razorpay_recon.csv", razorpay_recon),
        ("settlements", "razorpay_settlements.csv", settlements),
        ("bank_statement", "bank_statement.csv", bank_statement),
    )
    for source_type, filename, content in uploads:
        response = client.post(
            "/api/sources/upload",
            data={"source_type": source_type},
            files={"file": (filename, content, "text/csv")},
        )
        assert response.status_code == 200, response.text
        source_ids.append(response.json()["source_id"])
    snapshot = client.post("/api/snapshots", json={"source_ids": source_ids})
    assert snapshot.status_code == 200, snapshot.text
    return snapshot.json()["snapshot_id"]


def test_demo_initializer_uses_ingestion_and_builds_snapshot(tmp_path) -> None:
    """A shortcut with precomputed decisions would not create accepted source evidence."""
    with make_client(tmp_path) as client:
        response = client.post("/api/demo/seed")
        assert response.status_code == 200
        payload = response.json()
        assert payload["identity_mode"] == "INSECURE_DEMO_CONTEXT"
        assert payload["record_count"] >= 250
        assert len(payload["source_ids"]) == 4
        assert payload["snapshot_id"].startswith("snapshot_")
        sources = client.get("/api/sources").json()["items"]
        assert {source["state"] for source in sources} == {"ACCEPTED"}


def test_demo_run_builds_live_verified_refused_pending_and_unresolved_results(tmp_path) -> None:
    """The vertical slice must exercise policy branches from current ingested rows."""
    with make_client(tmp_path) as client:
        client.post("/api/demo/seed")
        response = client.post("/api/runs", json={})
        assert response.status_code == 200
        run = response.json()
        rows = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"]
        decisions = {row["decision"] for row in rows}
        assert {"AUTO_VERIFIED", "REFUSED", "PENDING", "UNRESOLVED", "REVIEW_REQUIRED"} <= decisions
        assert run["records_processed"] >= 250
        assert run["total_ms"] >= 0
        assert run["source_snapshot_id"].startswith("snapshot_")
        verified = next(row for row in rows if row["decision"] == "AUTO_VERIFIED")
        assert verified["proof_id"].startswith("proof_")


def test_run_summary_is_derived_from_rows(tmp_path) -> None:
    """A hardcoded summary would diverge from persisted settlement decisions."""
    with make_client(tmp_path) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        rows = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"]
        expected = sum(row["expected_paise"] for row in rows)
        explained = sum(row["expected_paise"] for row in rows if row["decision"] == "AUTO_VERIFIED")
        assert run["expected_paise"] == expected
        assert run["explained_paise"] == explained
        assert run["unresolved_paise"] == expected - explained


def test_demo_run_uses_current_v2_rule_configuration_and_policy_keys(tmp_path) -> None:
    """The active run must persist the v2 rule/config identity and never serialize the legacy policy key."""
    with make_client(tmp_path) as client:
        client.post("/api/demo/seed")
        response = client.post("/api/runs", json={})
        assert response.status_code == 200
        run = response.json()
        row = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"][0]
        proof = client.get(f"/api/proofs/{row['proof_id']}").json()

    assert run["rule_version"] == "2.0"
    assert run["configuration_version"] == "2.0"
    assert proof["rule_name"] == "settlement_match"
    assert proof["rule_version"] == "2.0"
    assert proof["configuration"] == {
        "version": "2.0",
        "values": {
            "pending_hours": 3,
            "bank_match_window_hours": 48,
            "early_bank_tolerance_hours": 2,
            "future_clock_skew_minutes": 5,
        },
    }
    assert proof["evidence_inputs"]["policy"] == proof["configuration"]["values"]
    assert "amount_candidate_window_hours" not in proof["evidence_inputs"]["policy"]


def test_order_excess_creates_a_dedicated_order_proof_without_bank_or_settlement_rows(tmp_path) -> None:
    """Order overpayment must stay separate from settlement lineage and unresolved close money."""
    with make_client(tmp_path) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        rows = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"]
        exceptions = client.get(f"/api/exceptions?run_id={run['run_id']}").json()["items"]
        item = next(x for x in exceptions if x["exception_type"] == "UNEXPECTED_MULTIPLE_SETTLED_PAYMENTS")
        proof = client.get(f"/api/proofs/{item['proof_id']}").json()

    assert proof["subject"] == {"subject_type": "ORDER", "subject_id": "order_PC0061"}
    assert proof["rule_name"] == "order_payment_consistency"
    assert proof["rule_version"] == "1.0"
    assert proof["configuration"]["version"] == "2.0"
    assert proof["result"]["delta_paise"] == item["amount_paise"]
    assert proof["evidence"]["excess_payment_paise"] == item["amount_paise"]
    assert {row["table"] for row in proof["source_rows"]} == {"merchant_orders", "razorpay_recon"}
    assert sum(row["table"] == "merchant_orders" for row in proof["source_rows"]) == 1
    assert all(row["table"] != "settlements" for row in proof["source_rows"])
    assert all(row["table"] != "bank_statement" for row in proof["source_rows"])
    assert {row["order_id"] for row in proof["evidence_inputs"]["payment_rows"]} == {"order_PC0061"}
    assert {row["type"] for row in proof["evidence_inputs"]["payment_rows"]} == {"payment"}
    assert run["unresolved_paise"] == sum(row["expected_paise"] for row in rows if row["decision"] != "AUTO_VERIFIED")


def test_ambiguous_settlement_proof_lists_all_candidates_and_no_unrelated_bank_rows(tmp_path) -> None:
    """Ambiguous settlement lineage must cite every credible bank candidate and nothing else."""
    with make_client(tmp_path) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        rows = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"]
        ambiguous = next(row for row in rows if row["settlement_id"] == "setl_PC010")
        proof = client.get(f"/api/proofs/{ambiguous['proof_id']}").json()

    bank_rows = proof["evidence_inputs"]["bank_lines"]
    lineage_bank_rows = [row for row in proof["source_rows"] if row["table"] == "bank_statement"]

    assert ambiguous["decision"] == "REFUSED"
    assert ambiguous["exception_type"] == "AMBIGUOUS_MATCH"
    assert proof["evidence"]["candidate_count"] == 2
    assert {row["bank_ref"] for row in bank_rows} == {"bank_PC010A", "bank_PC010B"}
    assert all("narration" not in row for row in bank_rows)
    assert len(lineage_bank_rows) == 2


def test_every_close_blocking_non_automatic_settlement_has_a_review_item_or_system_blocker(tmp_path) -> None:
    """No blocking settlement should be invisible to the review and close layers."""
    with make_client(tmp_path) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        rows = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"]
        exceptions = client.get(f"/api/exceptions?run_id={run['run_id']}").json()["items"]

    exception_proof_ids = {item["proof_id"] for item in exceptions}
    for row in rows:
        if row["decision"] in {"AUTO_VERIFIED", "PENDING"}:
            continue
        if row["decision"] == "SYSTEM_ERROR":
            assert row["proof_id"] not in exception_proof_ids
            continue
        assert row["exception_type"] is not None
        assert row["proof_id"] in exception_proof_ids


def test_nonprocessable_settlements_remain_visible_but_contribute_zero_close_money(tmp_path) -> None:
    """Refused failed settlements should still create reviewable proofs without inflating close totals."""
    merchant_orders = (
        b"order_id,amount_paise,amount_paid_paise,amount_due_paise,currency,status,partial_payment,attempts,created_at\n"
        b"order_ok,10000,10000,0,INR,paid,false,1,2026-08-26T03:00:00Z\n"
        b"order_failed,5000,5000,0,INR,paid,false,1,2026-08-26T03:00:00Z\n"
    )
    razorpay_recon = (
        b"entity_id,type,debit,credit,amount,currency,fee,tax,on_hold,settled,created_at,settled_at,settlement_id,payment_id,settlement_utr,order_id,order_receipt\n"
        b"pay_ok,payment,0,10000,10000,INR,0,0,false,true,1787713200,1787724000,setl_ok,,UTR_OK,order_ok,receipt_ok\n"
        b"pay_failed,payment,0,5000,5000,INR,0,0,false,true,1787713200,1787724000,setl_failed,,UTR_FAILED,order_failed,receipt_failed\n"
    )
    settlements = (
        b"id,amount,status,fees,tax,utr,created_at\n"
        b"setl_ok,10000,processed,0,0,UTR_OK,1787724000\n"
        b"setl_failed,5000,failed,0,0,UTR_FAILED,1787724000\n"
    )
    bank_statement = (
        b"bank_ref,utr,credit_amount_paise,value_date,narration\n"
        b"bank_ok,UTR_OK,10000,2026-08-26T08:00:00Z,SETTLEMENT\n"
        b"bank_failed,UTR_FAILED,5000,2026-08-26T08:00:00Z,SETTLEMENT\n"
    )
    with make_client(tmp_path) as client:
        snapshot_id = upload_snapshot(
            client,
            merchant_orders=merchant_orders,
            razorpay_recon=razorpay_recon,
            settlements=settlements,
            bank_statement=bank_statement,
        )
        response = client.post("/api/runs", json={"snapshot_id": snapshot_id})
        assert response.status_code == 200
        run = response.json()
        rows = {row["settlement_id"]: row for row in client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"]}

    assert rows["setl_ok"]["decision"] == "AUTO_VERIFIED"
    assert rows["setl_failed"]["decision"] == "REFUSED"
    assert rows["setl_failed"]["exception_type"] == "NON_PROCESSABLE_SETTLEMENT_STATUS"
    assert rows["setl_failed"]["expected_paise"] == 0
    assert run["expected_paise"] == 10_000
    assert run["explained_paise"] == 10_000
    assert run["unresolved_paise"] == 0


def test_health_reports_optional_model_without_requiring_it(tmp_path) -> None:
    """Missing model credentials must not stop deterministic startup."""
    with make_client(tmp_path) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["deterministic_reconciliation"] == "available"
        assert health["ai_assistance"] == "evidence_mode"
        assert health["provider"]["configuration_status"] == "not_configured"
        assert health["provider"]["reachability_status"] == "not_probed"


def test_health_distinguishes_configured_from_successfully_reachable(tmp_path) -> None:
    """Having a key is not evidence that the provider endpoint has worked."""
    placeholder = "provider-placeholder-value"
    settings = Settings(
        PROOFCLOSE_ENV="demo",
        PROOFCLOSE_DATA_DIR=tmp_path,
        **{"NVIDIA_API_KEY": placeholder},
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")

    health = response.json()
    assert health["ai_assistance"] == "ai_assisted_evidence_mode"
    assert health["provider"]["configuration_status"] == "configured"
    assert health["provider"]["reachability_status"] == "not_probed"
    assert placeholder not in response.text


class _UnsupportedNarrationProvider:
    def __init__(self) -> None:
        self.reachable = False
        self.plan_calls = 0
        self.narration_calls = 0

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            configuration_status="configured",
            reachability_status="reachable" if self.reachable else "not_probed",
            model="test-provider-model",
        )

    def plan(
        self,
        _question: str,
        context: AssistantContext,
        _allowed_tools: tuple[str, ...],
        *,
        attempt_guard=None,
    ) -> tuple[ToolSelection, ProviderResult]:
        if attempt_guard is not None and not attempt_guard():
            raise ProviderFailure("provider_budget_exhausted")
        self.plan_calls += 1
        self.reachable = True
        return (
            ToolSelection(name="close_summary", arguments={"run_id": context.run_id}, route="PLANNER_TOOL"),
            ProviderResult(content="{}", input_tokens=11, output_tokens=3, model="test-provider-model", latency_ms=4),
        )

    def narrate(self, _question: str, _tool_name: str, _canonical: dict, *, attempt_guard=None) -> ProviderResult:
        if attempt_guard is not None and not attempt_guard():
            raise ProviderFailure("provider_budget_exhausted")
        self.narration_calls += 1
        return ProviderResult(
            content="The unexplained amount is ₹999.",
            input_tokens=13,
            output_tokens=5,
            model="test-provider-model",
            latency_ms=6,
        )


class _RefusingPlannerProvider(_UnsupportedNarrationProvider):
    def plan(
        self,
        _question: str,
        _context: AssistantContext,
        _allowed_tools: tuple[str, ...],
        *,
        attempt_guard=None,
    ) -> tuple[ToolSelection, ProviderResult]:
        if attempt_guard is not None and not attempt_guard():
            raise ProviderFailure("provider_budget_exhausted")
        self.plan_calls += 1
        self.reachable = True
        return (
            ToolSelection(name="REFUSE", arguments={}, route="REFUSE", reason="Outside the evidence boundary"),
            ProviderResult(content='{"name":"REFUSE","arguments":{}}', input_tokens=7, output_tokens=3, model="test-provider-model"),
        )


def test_usage_is_observed_and_unsupported_narration_falls_back_to_canonical_facts(tmp_path) -> None:
    """The assistant must count, reject, and observe model-added financial claims."""
    app = create_app(
        Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path),
        assistant_provider=_UnsupportedNarrationProvider(),
    )
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        answer = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "Please analyze whatever matters most."},
        ).json()
        diagnostics = client.get(f"/api/ops/diagnostics?run_id={run['run_id']}").json()

    assert answer["route"] == "PLANNER_TOOL"
    assert answer["canonical"]
    assert answer["narration"] is None
    assert answer["narration_status"] == "rejected_unsupported_claims"
    assert answer["unsupported_factual_claims"] == 1
    assert answer["estimated_cost"] == "unavailable"
    assert diagnostics["llm_calls"] == 2
    assert diagnostics["llm_input_tokens"] == 24
    assert diagnostics["llm_output_tokens"] == 8
    assert diagnostics["estimated_llm_cost"] == "unavailable"


def test_direct_supported_question_makes_zero_provider_calls(tmp_path) -> None:
    """Recognizable evidence questions must stay deterministic even with AI configured."""
    provider = _UnsupportedNarrationProvider()
    app = create_app(
        Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path),
        assistant_provider=provider,
    )
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        answer = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "What prevents today's close?"},
        ).json()
        diagnostics = client.get(f"/api/ops/diagnostics?run_id={run['run_id']}").json()

    assert answer["route"] == "DIRECT_TOOL"
    assert provider.plan_calls == 0
    assert provider.narration_calls == 0
    assert diagnostics["llm_calls"] == 0


def test_provider_refusal_is_safe_and_does_not_execute_or_narrate(tmp_path) -> None:
    provider = _RefusingPlannerProvider()
    app = create_app(
        Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path),
        assistant_provider=provider,
    )
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        answer = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "Forecast next year's card mix"},
        ).json()

    assert answer["status"] == "REFUSED"
    assert answer["route"] == "REFUSE"
    assert answer["tool_name"] is None
    assert answer["canonical"] == {}
    assert answer["narration"] is None
    assert provider.plan_calls == 1
    assert provider.narration_calls == 0


def test_failed_http_attempt_then_denied_retry_is_observed_without_extra_request(tmp_path) -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="secret provider body must not escape")

    provider = NvidiaProvider(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/test-model",
        timeout_seconds=1,
        max_retries=2,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    app = create_app(
        Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path),
        assistant_provider=provider,
    )
    app.state.investigations.budget = ProviderCallBudget(limit=1)
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        answer_response = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "Analyze the most important evidence"},
        )
        diagnostics = client.get(f"/api/ops/diagnostics?run_id={run['run_id']}").json()

    answer = answer_response.json()
    assert answer_response.status_code == 200
    assert answer["narration_status"] == "provider_budget_exhausted"
    assert answer["provider"]["reachability_status"] == "unreachable"
    assert answer["provider"]["failure_category"] == "provider"
    assert answer["provider"]["last_probe_at"].endswith("Z")
    assert calls == 1
    assert diagnostics["llm_calls"] == 1
    assert diagnostics["estimated_llm_cost"] == "unavailable"
    assert "secret provider body" not in answer_response.text


def test_planning_budget_exhaustion_makes_zero_provider_calls_and_is_observed(tmp_path) -> None:
    provider = _UnsupportedNarrationProvider()
    app = create_app(
        Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path),
        assistant_provider=provider,
    )
    app.state.investigations.budget = ProviderCallBudget(limit=0)
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        answer = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "Analyze the most important evidence"},
        ).json()
        diagnostics = client.get(f"/api/ops/diagnostics?run_id={run['run_id']}").json()

    assert answer["narration_status"] == "provider_budget_exhausted"
    assert provider.plan_calls == 0
    assert provider.narration_calls == 0
    assert diagnostics["llm_calls"] == 0


def test_narration_budget_exhaustion_makes_no_extra_provider_call_and_is_observed(tmp_path) -> None:
    provider = _UnsupportedNarrationProvider()
    app = create_app(
        Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path),
        assistant_provider=provider,
    )
    app.state.investigations.budget = ProviderCallBudget(limit=1)
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        answer = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "Analyze the most important evidence"},
        ).json()
        diagnostics = client.get(f"/api/ops/diagnostics?run_id={run['run_id']}").json()

    assert answer["narration_status"] == "provider_budget_exhausted"
    assert provider.plan_calls == 1
    assert provider.narration_calls == 0
    assert diagnostics["llm_calls"] == 1


def test_rejected_provider_output_still_records_observed_usage(tmp_path) -> None:
    responses = iter(
        [
            ("{\"name\":\"close_summary\",\"arguments\":{\"run_id\":\"ignored\"}}", 11, 3),
            ("{\"fact_keys\":[\"invented\"]}", 13, 4),
        ]
    )

    def respond(_request: httpx.Request) -> httpx.Response:
        content, input_tokens, output_tokens = next(responses)
        return httpx.Response(
            200,
            json={
                "model": "nvidia/test-model",
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
            },
        )

    provider = NvidiaProvider(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/test-model",
        timeout_seconds=1,
        max_retries=0,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    app = create_app(
        Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path),
        assistant_provider=provider,
    )
    with TestClient(app) as client:
        client.post("/api/demo/seed")
        run = client.post("/api/runs", json={}).json()
        answer = client.post(
            "/api/investigations/query",
            json={"run_id": run["run_id"], "question": "Analyze the most important evidence"},
        ).json()
        diagnostics = client.get(f"/api/ops/diagnostics?run_id={run['run_id']}").json()

    assert answer["narration_status"] == "provider_unavailable"
    assert answer["narration"] is None
    assert diagnostics["llm_calls"] == 2
    assert diagnostics["llm_input_tokens"] == 24
    assert diagnostics["llm_output_tokens"] == 7
    assert diagnostics["estimated_llm_cost"] == "unavailable"


def test_snapshot_endpoint_freezes_selected_accepted_sources(tmp_path) -> None:
    """Reviewers can create an explicit snapshot instead of relying on demo-only state."""
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))
    with TestClient(app) as client:
        demo = client.post("/api/demo/seed").json()
        response = client.post("/api/snapshots", json={"source_ids": demo["source_ids"]})
    app.state.database.dispose()
    app.state.observability.dispose()

    assert response.status_code == 200
    assert response.json()["snapshot_id"] == demo["snapshot_id"]


def test_uploaded_settlement_without_recon_evidence_creates_partial_system_result(tmp_path) -> None:
    """Incomplete cross-source evidence must be durable and explicit rather than a server crash."""
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        demo = client.post("/api/demo/seed").json()
        sources = client.get("/api/sources").json()["items"]
        retained = [item["source_id"] for item in sources if item["source_type"] != "settlements"]
        orphan_csv = (
            b"id,amount,status,utr,created_at,fees,tax\n"
            b"setl_orphan,10000,processed,UTR_ORPHAN,2026-08-26T08:00:00+00:00,0,0\n"
        )
        upload = client.post(
            "/api/sources/upload",
            data={"source_type": "settlements"},
            files={"file": ("orphan-settlement.csv", orphan_csv, "text/csv")},
        )
        snapshot = client.post(
            "/api/snapshots",
            json={"source_ids": [*retained, upload.json()["source_id"]]},
        ).json()
        response = client.post("/api/runs", json={"snapshot_id": snapshot["snapshot_id"]})
    app.state.database.dispose()
    app.state.observability.dispose()

    assert demo["record_count"] >= 250
    assert upload.status_code == 200
    assert response.status_code == 200
    run = response.json()
    assert run["state"] == "PARTIAL"
    with TestClient(create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))) as client:
        rows = client.get(f"/api/runs/{run['run_id']}/settlements").json()["items"]
    assert rows[0]["decision"] == "SYSTEM_ERROR"


def test_unexpected_run_failure_is_persisted_as_failed(tmp_path, monkeypatch) -> None:
    """A stage crash must leave a durable failed run instead of disappearing behind HTTP 500."""
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        client.post("/api/demo/seed")

        def fail_proof_creation(*_args, **_kwargs):
            raise RuntimeError("simulated proof stage failure")

        monkeypatch.setattr(app.state.proof_service, "create", fail_proof_creation)
        response = client.post("/api/runs", json={})
        latest = client.get("/api/runs/latest").json()
    app.state.database.dispose()
    app.state.observability.dispose()

    assert response.status_code == 500
    assert latest["state"] == "FAILED"
    assert latest["total_ms"] >= 0
