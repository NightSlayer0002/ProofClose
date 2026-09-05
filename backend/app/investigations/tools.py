from collections import defaultdict

from app.close.service import CloseService
from app.investigations.contracts import AssistantCitations, ToolSelection
from app.proofs.service import ProofService
from app.review.service import ReviewService
from app.runs.service import RunService


class FinanceTools:
    def __init__(
        self,
        runs: RunService,
        reviews: ReviewService,
        proofs: ProofService | None = None,
        close: CloseService | None = None,
    ) -> None:
        self.runs = runs
        self.reviews = reviews
        self.proofs = proofs
        self.close = close

    def execute(self, tenant_id: str, selection: ToolSelection) -> dict:
        dispatch = {
            "close_summary": self.close_summary,
            "close_blockers": self.close_blockers,
            "settlement_lookup": self.settlement_lookup,
            "exception_breakdown": self.exception_breakdown,
            "pending_settlements": self.pending_settlements,
            "proof_explanation": self.proof_explanation,
            "source_lineage": self.source_lineage,
            "product_help": self.product_help,
        }
        if selection.name not in dispatch:
            raise ValueError("tool selection is not allowlisted")
        allowed_arguments = {
            "close_summary": {"run_id"},
            "close_blockers": {"run_id"},
            "settlement_lookup": {"run_id", "settlement_id"},
            "exception_breakdown": {"run_id"},
            "pending_settlements": {"run_id"},
            "proof_explanation": {"run_id", "proof_id"},
            "source_lineage": {"run_id", "proof_id"},
            "product_help": {"run_id"},
        }[selection.name]
        if set(selection.arguments) != allowed_arguments:
            raise ValueError("tool arguments are not allowlisted")
        return dispatch[selection.name](tenant_id, **selection.arguments)

    @staticmethod
    def _citations(*, proof_ids=(), source_rows=(), scope="DIRECT") -> dict:
        return AssistantCitations(
            proof_ids=tuple(proof_ids), source_rows=tuple(source_rows), support_scope=scope
        ).model_dump(mode="json")

    def _run_context(self, tenant_id: str, run_id: str) -> tuple[dict, int]:
        run = self.runs.get_run(tenant_id, run_id)
        return run, int(run["records_processed"])

    def close_summary(self, tenant_id: str, run_id: str) -> dict:
        run, run_record_count = self._run_context(tenant_id, run_id)
        return {
            "facts": {
                "run_id": run_id,
                "state": run["state"],
                "expected_paise": run["expected_paise"],
                "explained_paise": run["explained_paise"],
                "unresolved_paise": run["unresolved_paise"],
                "not_auto_verified_paise": run["unresolved_paise"],
            },
            "lines": [],
            "proof_ids": [],
            "citations": self._citations(scope="AGGREGATE"),
            "supporting_record_count": 1,
            "run_record_count": run_record_count,
            "calculation_count": 1,
        }

    def close_blockers(self, tenant_id: str, run_id: str) -> dict:
        run, run_record_count = self._run_context(tenant_id, run_id)
        if self.close is None:
            raise RuntimeError("close service is unavailable")
        close_state = self.close.get_state(tenant_id, run_id)
        rows = self.runs.list_results(tenant_id, run_id)
        blocking = [row for row in rows if row["decision"] not in {"AUTO_VERIFIED", "PENDING"}]
        used_rows = [*blocking, *[row for row in rows if row["decision"] == "PENDING"]]
        proof_ids = [row["proof_id"] for row in used_rows if row.get("proof_id")]
        for proof_id in proof_ids:
            self._proof(tenant_id, run_id, proof_id)
        return {
            "facts": {
                "run_id": run_id,
                "expected_paise": run["expected_paise"],
                "explained_paise": run["explained_paise"],
                "unresolved_paise": run["unresolved_paise"],
                "not_auto_verified_paise": run["unresolved_paise"],
                # blocking_count is kept as a compatibility alias. Public copy uses
                # the precise total_close_blockers vocabulary below.
                "blocking_count": close_state["total_close_blockers"],
                "settlement_exception_count": close_state["settlement_exception_count"],
                "review_item_count": close_state["review_item_count"],
                "open_review_item_count": (
                    close_state["review_item_count"] - close_state["manually_reviewed_count"]
                ),
                "total_close_blockers": close_state["total_close_blockers"],
                "pending_count": sum(row["decision"] == "PENDING" for row in rows),
                "unreviewable_blockers": close_state["unreviewable_blockers"],
                "system_error_blockers": close_state["system_error_blockers"],
                "integrity_blockers": close_state["integrity_blockers"],
            },
            "lines": [*blocking, *[row for row in rows if row["decision"] == "PENDING"]],
            "proof_ids": proof_ids,
            "citations": self._citations(proof_ids=proof_ids, scope="AGGREGATE"),
            "supporting_record_count": len(used_rows),
            "run_record_count": run_record_count,
            "calculation_count": 1,
        }

    def settlement_lookup(self, tenant_id: str, run_id: str, settlement_id: str) -> dict:
        _run, run_record_count = self._run_context(tenant_id, run_id)
        row = next((item for item in self.runs.list_results(tenant_id, run_id) if item["settlement_id"] == settlement_id), None)
        if row is None:
            raise KeyError(settlement_id)
        facts = {
            "settlement_id": row["settlement_id"],
            "utr": row["utr"],
            "expected_paise": row["expected_paise"],
            "observed_paise": row["observed_paise"],
            "difference_paise": row["difference_paise"],
            "decision": row["decision"],
            "exception_type": row["exception_type"],
            "candidate_count": row["evidence"]["candidate_count"],
            "evidence": row["evidence"],
            "reasons": row["reasons"],
            "proof_id": row["proof_id"],
        }
        proof = self._proof(tenant_id, run_id, row["proof_id"])
        source_rows = tuple(f"{item.table}:{item.id}" for item in proof.source_rows)
        return {
            "facts": facts,
            "lines": [row],
            "proof_ids": [row["proof_id"]],
            "citations": self._citations(
                proof_ids=[row["proof_id"]], source_rows=source_rows, scope="DIRECT"
            ),
            "supporting_record_count": 1,
            "run_record_count": run_record_count,
            "calculation_count": 0,
        }

    def exception_breakdown(self, tenant_id: str, run_id: str) -> dict:
        _run, run_record_count = self._run_context(tenant_id, run_id)
        grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "amount_paise": 0})
        for item in self.reviews.list_exceptions(tenant_id, run_id):
            group = grouped[item["exception_type"]]
            group["count"] += 1
            group["amount_paise"] += item["amount_paise"]
        groups = [{"exception_type": key, **value} for key, value in sorted(grouped.items())]
        return {
            "facts": {"run_id": run_id, "groups": groups},
            "lines": groups,
            "proof_ids": [],
            "citations": self._citations(scope="AGGREGATE"),
            "supporting_record_count": len(groups),
            "run_record_count": run_record_count,
            "calculation_count": 1,
        }

    def pending_settlements(self, tenant_id: str, run_id: str) -> dict:
        _run, run_record_count = self._run_context(tenant_id, run_id)
        pending = [row for row in self.runs.list_results(tenant_id, run_id) if row["decision"] == "PENDING"]
        proof_ids = [row["proof_id"] for row in pending if row.get("proof_id")]
        for proof_id in proof_ids:
            self._proof(tenant_id, run_id, proof_id)
        return {
            "facts": {"run_id": run_id, "pending_count": len(pending), "pending_paise": sum(row["expected_paise"] for row in pending)},
            "lines": pending,
            "proof_ids": [row["proof_id"] for row in pending],
            "citations": self._citations(
                proof_ids=proof_ids,
                scope="AGGREGATE",
            ),
            "supporting_record_count": len(pending),
            "run_record_count": run_record_count,
            "calculation_count": 1,
        }

    def _proof(self, tenant_id: str, run_id: str, proof_id: str):
        if self.proofs is None:
            raise RuntimeError("proof service is unavailable")
        proof = self.proofs.get(proof_id, tenant_id)
        if proof.run_id != run_id:
            raise KeyError(proof_id)
        return proof

    def proof_explanation(self, tenant_id: str, run_id: str, proof_id: str) -> dict:
        proof = self._proof(tenant_id, run_id, proof_id)
        facts = {
            "proof_id": proof.proof_id,
            "run_id": proof.run_id,
            "status": proof.status.value,
            "subject_id": proof.subject.subject_id,
            "subject_type": proof.subject.subject_type.value,
            "exception_type": proof.exception_type.value if proof.exception_type else None,
            "formula": proof.formula,
            "result": proof.result.model_dump(mode="json"),
            "evidence": proof.evidence.model_dump(mode="json"),
            "decision_reasons": list(proof.decision_reasons),
            "rule_name": proof.rule_name,
            "rule_version": proof.rule_version,
            "configuration_version": proof.configuration_version,
            "proof_fingerprint": proof.proof_fingerprint,
        }
        source_rows = tuple(f"{item.table}:{item.id}" for item in proof.source_rows)
        return {
            "facts": facts,
            "lines": [],
            "proof_ids": [proof.proof_id],
            "citations": self._citations(
                proof_ids=[proof.proof_id], source_rows=source_rows, scope="DIRECT"
            ),
            "supporting_record_count": len(proof.source_rows),
            "run_record_count": self.runs.get_run(tenant_id, run_id)["records_processed"],
            "calculation_count": 0,
        }

    def source_lineage(self, tenant_id: str, run_id: str, proof_id: str) -> dict:
        proof = self._proof(tenant_id, run_id, proof_id)
        source_rows = [row.model_dump(mode="json") for row in proof.source_rows]
        facts = {
            "proof_id": proof.proof_id,
            "run_id": proof.run_id,
            "source_snapshot_id": proof.source_snapshot_id,
            "source_rows": source_rows,
        }
        return {
            "facts": facts,
            "lines": source_rows,
            "proof_ids": [proof.proof_id],
            "citations": self._citations(
                proof_ids=[proof.proof_id],
                source_rows=tuple(f"{item.table}:{item.id}" for item in proof.source_rows),
                scope="DIRECT",
            ),
            "supporting_record_count": len(source_rows),
            "run_record_count": self.runs.get_run(tenant_id, run_id)["records_processed"],
            "calculation_count": 0,
        }

    def product_help(self, tenant_id: str, run_id: str) -> dict:
        _run, run_record_count = self._run_context(tenant_id, run_id)
        facts = {
            "title": "ProofClose workflow",
            "steps": ["Source CSVs", "Immutable snapshot", "Deterministic reconciliation", "Versioned proofs", "Human review", "Close policy"],
            "authority_boundary": "AI proposes; code computes; evidence proves; policy decides; humans control review and close.",
        }
        return {
            "facts": facts,
            "lines": [],
            "proof_ids": [],
            "citations": self._citations(scope="AGGREGATE"),
            "supporting_record_count": 0,
            "run_record_count": run_record_count,
            "calculation_count": 0,
        }
