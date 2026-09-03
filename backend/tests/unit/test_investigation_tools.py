from pathlib import Path

import pytest

from app.config import Settings
from app.investigations.contracts import AssistantContext, ToolSelection
from app.investigations.router import route_question
from app.main import create_app
from app.storage.schema import ProofRecord


@pytest.fixture()
def evidence_context(tmp_path: Path):
    app = create_app(Settings(PROOFCLOSE_ENV="demo", PROOFCLOSE_DATA_DIR=tmp_path))
    tenant_id = app.state.settings.demo_tenant_id
    source_ids = []
    from scripts.generate_demo import build_demo_files

    for source_type, (filename, content) in build_demo_files().items():
        source_ids.append(app.state.ingestion.ingest_csv(tenant_id, source_type, filename, content).source_id)
    snapshot = app.state.snapshots.create(tenant_id, source_ids)
    run = app.state.run_service.run_snapshot(tenant_id, snapshot.snapshot_id)
    yield app, tenant_id, run
    app.state.database.dispose()
    app.state.observability.dispose()


def test_selected_settlement_routes_to_lookup() -> None:
    selection = route_question(
        "Why was this refused?",
        AssistantContext(run_id="run_1", settlement_id="setl_PC010", page="reconciliation"),
    )
    assert selection == ToolSelection(
        name="settlement_lookup",
        arguments={"run_id": "run_1", "settlement_id": "setl_PC010"},
        route="DIRECT_TOOL",
        reason="Selected settlement supplies exact evidence context",
    )


@pytest.mark.parametrize(
    ("question", "tool_name"),
    [
        ("What is today's unresolved amount?", "close_summary"),
        ("What prevents today's close?", "close_blockers"),
        ("Break down exceptions by type", "exception_breakdown"),
        ("Which settlements are pending?", "pending_settlements"),
        ("How does ProofClose work?", "product_help"),
    ],
)
def test_known_questions_have_deterministic_routes(question: str, tool_name: str) -> None:
    assert route_question(question, AssistantContext(run_id="run_1")).name == tool_name


def test_unknown_question_has_no_deterministic_tool() -> None:
    assert route_question("Forecast next year's card mix", AssistantContext(run_id="run_1")).name == "REFUSE"


def test_close_summary_and_exception_breakdown_are_derived_from_the_run(evidence_context) -> None:
    app, tenant_id, run = evidence_context
    tools = app.state.investigations.tools
    summary = tools.execute(
        tenant_id,
        ToolSelection(name="close_summary", arguments={"run_id": run["run_id"]}),
    )
    breakdown = tools.execute(
        tenant_id,
        ToolSelection(name="exception_breakdown", arguments={"run_id": run["run_id"]}),
    )

    assert summary["facts"]["expected_paise"] == run["expected_paise"]
    assert summary["facts"]["unresolved_paise"] == run["unresolved_paise"]
    assert summary["calculation_count"] == 1
    assert sum(item["count"] for item in breakdown["facts"]["groups"]) == len(
        app.state.review_service.list_exceptions(tenant_id, run["run_id"])
    )
    assert all(item["amount_paise"] > 0 for item in breakdown["facts"]["groups"])


def test_close_blocker_tool_uses_the_canonical_close_count_vocabulary(evidence_context) -> None:
    app, tenant_id, run = evidence_context
    close_state = app.state.close_service.get_state(tenant_id, run["run_id"])
    report = app.state.investigations.tools.execute(
        tenant_id,
        ToolSelection(name="close_blockers", arguments={"run_id": run["run_id"]}),
    )

    facts = report["facts"]
    assert facts["settlement_exception_count"] == close_state["settlement_exception_count"]
    assert facts["review_item_count"] == close_state["review_item_count"]
    assert facts["open_review_item_count"] == (
        close_state["review_item_count"] - close_state["manually_reviewed_count"]
    )
    assert facts["total_close_blockers"] == close_state["total_close_blockers"]
    assert facts["system_error_blockers"] == close_state["system_error_blockers"]
    assert facts["integrity_blockers"] == close_state["integrity_blockers"]
    assert facts["not_auto_verified_paise"] == run["unresolved_paise"]


def test_settlement_and_proof_tools_return_scoped_canonical_evidence(evidence_context) -> None:
    app, tenant_id, run = evidence_context
    tools = app.state.investigations.tools
    row = next(
        item for item in app.state.run_service.list_results(tenant_id, run["run_id"])
        if item["settlement_id"] == "setl_PC010"
    )
    settlement = tools.execute(
        tenant_id,
        ToolSelection(
            name="settlement_lookup",
            arguments={"run_id": run["run_id"], "settlement_id": row["settlement_id"]},
        ),
    )
    proof = tools.execute(
        tenant_id,
        ToolSelection(
            name="proof_explanation",
            arguments={"run_id": run["run_id"], "proof_id": row["proof_id"]},
        ),
    )
    lineage = tools.execute(
        tenant_id,
        ToolSelection(
            name="source_lineage",
            arguments={"run_id": run["run_id"], "proof_id": row["proof_id"]},
        ),
    )

    assert settlement["facts"]["decision"] == "REFUSED"
    assert settlement["facts"]["candidate_count"] == 2
    assert settlement["proof_ids"] == [row["proof_id"]]
    assert proof["facts"]["rule_version"] == "2.0"
    assert proof["facts"]["formula"]
    assert lineage["facts"]["source_snapshot_id"] == run["source_snapshot_id"]
    assert all(source["raw_hash"].startswith("sha256:") for source in lineage["facts"]["source_rows"])


def test_citations_are_minimal_and_counts_separate_direct_support_from_run_context(evidence_context) -> None:
    app, tenant_id, run = evidence_context
    tools = app.state.investigations.tools
    row = app.state.run_service.list_results(tenant_id, run["run_id"])[0]
    direct = tools.execute(
        tenant_id,
        ToolSelection(
            name="settlement_lookup",
            arguments={"run_id": run["run_id"], "settlement_id": row["settlement_id"]},
        ),
    )
    aggregate = tools.execute(
        tenant_id,
        ToolSelection(name="close_summary", arguments={"run_id": run["run_id"]}),
    )

    assert direct["citations"]["support_scope"] == "DIRECT"
    assert direct["citations"]["proof_ids"] == [row["proof_id"]]
    assert direct["supporting_record_count"] == 1
    assert direct["run_record_count"] == run["records_processed"]
    assert aggregate["citations"]["support_scope"] == "AGGREGATE"
    assert aggregate["supporting_record_count"] == 1
    assert aggregate["run_record_count"] == run["records_processed"]


def test_aggregate_tools_never_return_citations_for_a_tampered_proof(evidence_context) -> None:
    app, tenant_id, run = evidence_context
    rows = app.state.run_service.list_results(tenant_id, run["run_id"])
    blocking_row = next(item for item in rows if item["decision"] not in {"AUTO_VERIFIED", "PENDING"})
    pending_row = next(item for item in rows if item["decision"] == "PENDING")
    with app.state.database.session() as session:
        for row in (blocking_row, pending_row):
            proof_record = session.get(ProofRecord, row["proof_id"])
            assert proof_record is not None
            proof_record.payload_json = proof_record.payload_json.replace('"status":', '"status":"tampered","original_status":')

    tools = app.state.investigations.tools
    with pytest.raises((KeyError, ValueError, RuntimeError)):
        tools.execute(tenant_id, ToolSelection(name="close_blockers", arguments={"run_id": run["run_id"]}))
    with pytest.raises((KeyError, ValueError, RuntimeError)):
        tools.execute(tenant_id, ToolSelection(name="pending_settlements", arguments={"run_id": run["run_id"]}))


def test_tool_rejects_injected_argument_names(evidence_context) -> None:
    _app, tenant_id, run = evidence_context
    with pytest.raises(ValueError, match="allowlisted"):
        _app.state.investigations.tools.execute(
            tenant_id,
            ToolSelection(
                name="close_summary",
                arguments={"run_id": run["run_id"], "tenant_id": "other"},
            ),
        )


def test_tool_lookup_does_not_cross_tenant_boundary(evidence_context) -> None:
    app, _tenant_id, run = evidence_context
    with pytest.raises(KeyError):
        app.state.investigations.tools.execute(
            "other_tenant",
            ToolSelection(name="close_summary", arguments={"run_id": run["run_id"]}),
        )


def test_proof_tools_do_not_cross_run_boundary(evidence_context) -> None:
    app, tenant_id, first_run = evidence_context
    first_row = app.state.run_service.list_results(tenant_id, first_run["run_id"])[0]
    second_run = app.state.run_service.run_snapshot(tenant_id, first_run["source_snapshot_id"])

    with pytest.raises(KeyError):
        app.state.investigations.tools.execute(
            tenant_id,
            ToolSelection(
                name="proof_explanation",
                arguments={"run_id": second_run["run_id"], "proof_id": first_row["proof_id"]},
            ),
        )
