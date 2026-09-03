from __future__ import annotations

from typing import Any

import re

from app.investigations.contracts import (
    ANSWER_LABELS,
    AssistantAnswer,
    AssistantContext,
    ConversationTurn,
    ProviderStatus,
    ToolSelection,
)
from app.investigations.provider import (
    TOOL_ARGUMENTS,
    AssistantProvider,
    ProviderCallBudget,
    ProviderFailure,
    validate_narration,
)
from app.investigations.router import route_question
from app.investigations.router import classify_copilot_intent
from app.investigations.tools import FinanceTools
from app.observability.store import ObservabilityStore
from app.presentation.currency import format_inr_paise
from app.investigations.guidance import guidance_for


ALLOWED_PROVIDER_TOOLS = (
    "close_summary",
    "close_blockers",
    "settlement_lookup",
    "exception_breakdown",
    "pending_settlements",
    "proof_explanation",
    "source_lineage",
    "product_help",
)


def offline_status() -> ProviderStatus:
    return ProviderStatus(
        configuration_status="not_configured",
        reachability_status="not_probed",
    )


def _report_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for row in lines:
        if {"expected_paise", "decision", "proof_id"} <= row.keys():
            report.append(
                {
                    "amount_paise": row["expected_paise"],
                    "label": row.get("exception_type") or row["decision"],
                    "classification": "OBSERVED" if row["decision"] == "PENDING" else "UNRESOLVED",
                    "proof_id": row["proof_id"],
                }
            )
        elif {"amount_paise", "exception_type"} <= row.keys():
            report.append(
                {
                    "amount_paise": row["amount_paise"],
                    "label": row["exception_type"],
                    "classification": "CALCULATED",
                    "proof_id": "",
                }
            )
    return report


def _deterministic_message(tool_name: str, canonical: dict) -> str:
    if tool_name == "general_help":
        return "I can explain ProofClose, reconciliation, UTRs, integer paise, evidence, proofs, exceptions, and close readiness."
    if tool_name == "unable_to_verify":
        return "I can help with ProofClose operations, but I cannot verify or perform that request."
    if tool_name == "close_blockers" and isinstance(canonical.get("blocking_count"), int):
        blockers = canonical["blocking_count"]
        pending = canonical.get("pending_count", 0)
        unresolved = canonical.get("unresolved_paise")
        amount = f" {format_inr_paise(unresolved)} remains unresolved." if isinstance(unresolved, int) and not isinstance(unresolved, bool) else ""
        return f"{blockers} close blockers and {pending} pending settlements remain in the verified run.{amount}"
    if tool_name == "exception_breakdown" and isinstance(canonical.get("groups"), list):
        groups = [group for group in canonical["groups"] if isinstance(group, dict)]
        count = sum(group.get("count", 0) for group in groups if isinstance(group.get("count"), int))
        amount_paise = sum(group.get("amount_paise", 0) for group in groups if isinstance(group.get("amount_paise"), int) and not isinstance(group.get("amount_paise"), bool))
        return f"{count} exceptions are recorded across {len(groups)} types, totalling {format_inr_paise(amount_paise)}."
    if tool_name == "pending_settlements" and isinstance(canonical.get("pending_count"), int):
        pending = canonical["pending_count"]
        amount = canonical.get("pending_paise")
        if isinstance(amount, int) and not isinstance(amount, bool):
            return f"{pending} pending settlements account for {format_inr_paise(amount)} in the verified run."
        return f"{pending} pending settlements remain in the verified timing window."
    if tool_name == "settlement_lookup":
        expected = canonical.get("expected_paise")
        observed = canonical.get("observed_paise")
        difference = canonical.get("difference_paise")
        decision = canonical.get("decision")
        if isinstance(expected, int) and isinstance(difference, int):
            expected_text = format_inr_paise(expected)
            difference_text = format_inr_paise(difference)
            if isinstance(observed, int):
                return f"This settlement expects {expected_text}; the verified bank credit is {format_inr_paise(observed)}, a difference of {difference_text}. Decision: {decision}."
            return f"No verified bank credit is linked to this settlement. Expected: {expected_text}; unresolved difference: {difference_text}. Decision: {decision}."
        if canonical.get("status"):
            return f"The verified proof status is {canonical['status']}."
    if "unresolved_paise" in canonical and tool_name == "close_summary":
        return f"{format_inr_paise(canonical['unresolved_paise'])} is currently unresolved in the verified run."
    if "unresolved_paise" in canonical and tool_name == "close_blockers":
        return f"{format_inr_paise(canonical['unresolved_paise'])} is currently unresolved in the verified evidence."
    if tool_name == "proof_explanation":
        proof_id = canonical.get("proof_id", "the selected proof")
        rule = canonical.get("rule_name")
        version = canonical.get("rule_version")
        return f"{proof_id} records the verified decision using {rule}@{version}. Its formula and evidence are shown below."
    messages = {
        "close_summary": "The current run summary is calculated from persisted reconciliation results.",
        "close_blockers": "These unresolved and pending items determine whether the current close can proceed.",
        "settlement_lookup": "This settlement decision comes from the displayed evidence predicates and versioned proof.",
        "exception_breakdown": "Exceptions are grouped by their persisted exception type.",
        "pending_settlements": "These settlements remain inside the configured bank-credit timing window.",
        "proof_explanation": "The formula, evidence predicates, and versions below are copied from the Proof Object.",
        "source_lineage": "These source references and hashes are bound to the selected Proof Object.",
    }
    return messages.get(
        tool_name,
        str(canonical.get("authority_boundary") or "ProofClose connects source evidence to deterministic proofs and human-controlled close policy."),
    )


class InvestigationService:
    def __init__(
        self,
        tools: FinanceTools,
        provider: AssistantProvider | None = None,
        observability: ObservabilityStore | None = None,
        budget: ProviderCallBudget | None = None,
    ) -> None:
        self.tools = tools
        self.provider = provider
        self.observability = observability
        self.budget = budget or ProviderCallBudget(2)

    @staticmethod
    def _validate_question(question: str) -> str:
        if not isinstance(question, str):
            raise ValueError("question must be text")
        if not question.strip() or not any(char.isprintable() and not char.isspace() for char in question):
            raise ValueError("question must contain visible text")
        return question.strip()[:1000]

    def provider_status(self) -> ProviderStatus:
        return self.provider.status() if self.provider else offline_status()

    @staticmethod
    def _sanitize_history_content(content: str) -> str:
        """Keep only conversational text; omit anything that could be evidence."""
        content = content[:500]
        sensitive = (
            r"(?i)(?:₹|\bINR\b|\b\d[\d,]*(?:\.\d+)?\b|%|\b(?:202\d|203\d)[-/]\d{1,2}[-/]\d{1,2}\b|"
            r"REVIEW_REQUIRED|AUTO_VERIFIED|REFUSED|UNRESOLVED|PENDING|SYSTEM_ERROR|"
            r"(?:proof|run|snapshot|setl|pay|rfnd|raw|bank)_[A-Za-z0-9_-]+|\bUTR[A-Za-z0-9_-]+\b|"
            r"source[_ ]?id|source[_ ]?hash|canonical|payload|narration|provider|tool|csv|bank_secret|"
            r"nvidia_api_key|openai_api_key|api[_ -]?key|sk-[A-Za-z0-9_-]{8,}|nvapi-[A-Za-z0-9_-]{8,}|"
            r"current\s+(?:run|status|amount|count|percentage|date)|selected\s+(?:settlement|proof)|"
            r"\b(?:settlement|proof|bank)\b|"
            r"\b[A-Za-z_]+(?:\s*,\s*[A-Za-z_]+){2,}\b|"
            r"\b(?:blocked|missing|unresolved|pending|exception|status|amount|percentage|count)\b|"
            r"\b(?:approve|reject|reset|upload|delete)\b)"
        )
        if re.search(sensitive, content):
            return "[previous turn omitted]"
        return content

    @staticmethod
    def _history(history: list[dict] | tuple[ConversationTurn, ...] | None) -> tuple[ConversationTurn, ...]:
        if not history:
            return ()
        turns: list[ConversationTurn] = []
        for item in history[-6:]:
            if isinstance(item, ConversationTurn):
                turns.append(ConversationTurn(role=item.role, content=InvestigationService._sanitize_history_content(item.content)))
            elif isinstance(item, dict):
                content = InvestigationService._sanitize_history_content(str(item.get("content", "")))
                turns.append(ConversationTurn.model_validate({"role": item.get("role"), "content": content}))
        return tuple(turns)

    @staticmethod
    def _general_response_is_safe(content: str) -> bool:
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 1200:
            return False
        if re.search(r"(?i)(nvidia_api_key|openai_api_key|nvapi-|sk-[a-z0-9_-]{8,}|api key)", content):
            return False
        if re.search(r"\b(?:proof|run|setl|pay|rfnd|raw|bank)_[A-Za-z0-9_-]+\b|\bUTR[A-Za-z0-9_-]+\b", content, re.I):
            return False
        if re.search(r"₹\s*[-+]?\d|\b\d[\d,]*\.\d{2}\b", content):
            return False
        if re.search(r"(?i)\b(?:approve|reject|reset|upload|delete)\b", content):
            return False
        if re.search(r"(?i)\b(?:REVIEW_REQUIRED|AUTO_VERIFIED|REFUSED|UNRESOLVED|PENDING|SYSTEM_ERROR)\b", content):
            return False
        if re.search(r"(?i)\b(?:current|active|selected)\s+(?:run|status|amount|count|percentage|date|settlement|proof)\b", content):
            return False
        if re.search(r"(?i)\b(?:status|amount|count|percentage|date)\s*(?:is|:)", content):
            return False
        if re.search(r"\b\d[\d,]*(?:\.\d+)?\b|%|\b(?:20\d\d|21\d\d)[-/]\d{1,2}[-/]\d{1,2}\b", content):
            return False
        if re.search(r"(?i)(?:source[_ ]?id|source[_ ]?hash|raw[_ ]?(?:row|payload|narration)|canonical|provider[_ ]?(?:response|message)|\b(?:csv|json)\b)", content):
            return False
        if re.search(r"\b[A-Za-z_]+(?:\s*,\s*[A-Za-z_]+){2,}\b", content):
            return False
        if re.search(r"(?i)(?:system\s+prompt|developer\s+message|hidden\s+(?:prompt|instruction)|tool\s+schema|ignore\s+previous)", content):
            return False
        return True

    def _general_help(self, tenant_id: str, run_id: str, question: str, history: tuple[ConversationTurn, ...]) -> dict:
        content: str | None = None
        narration_status = "deterministic_fallback"
        if self.provider is not None and callable(getattr(self.provider, "general_help", None)):
            try:
                result = self.provider.general_help(
                    question,
                    history,
                    before_attempt=lambda: self.budget.consume(tenant_id, run_id),
                )
                self._record_provider_call(tenant_id, run_id, "general_help", result=result)
                if self._general_response_is_safe(result.content):
                    content = result.content.strip()
                    narration_status = "accepted"
                else:
                    narration_status = "rejected_unsafe_output"
            except ProviderFailure as failure:
                if failure.category != "provider_budget_exhausted" or failure.result is not None:
                    self._record_provider_call(tenant_id, run_id, "general_help", result=failure.result, failure=failure, failure_category=failure.attempt_category)
                narration_status = "provider_budget_exhausted" if failure.category == "provider_budget_exhausted" else "provider_unavailable"
            except (TypeError, ValueError):
                narration_status = "provider_unavailable"
        if content is None:
            normalized = " ".join(question.lower().split())
            if normalized in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:
                content = "Hi — I’m the ProofClose Evidence Copilot. I can explain reconciliation, UTRs, proofs, exceptions, and what to check next."
            elif "utr" in normalized:
                content = "A UTR is a bank reference used to trace a payment. ProofClose compares it with the settlement evidence and keeps the result tied to its source proof."
            elif "paise" in normalized:
                content = "ProofClose stores money as integer paise, the smallest currency unit. That keeps comparisons exact and makes the proof fingerprint reproducible."
            elif "what can you help" in normalized or "how do i use" in normalized:
                content = "I can explain the active ProofClose workflow, settlement evidence, proofs, exceptions, and close readiness. Current amounts and statuses are checked from the run when you ask about them."
            elif "proof" in normalized:
                content = "A proof is the small, tamper-evident record that connects a decision to the exact rule, configuration, and source rows that support it."
            elif "exception" in normalized:
                content = "An exception is an item that deterministic checks could not safely close automatically. It stays visible for evidence review and a human decision."
            elif "reconciliation" in normalized:
                content = "Reconciliation compares expected settlement records with bank evidence, allocates each bank credit once, and records a versioned result."
            elif "close" in normalized:
                content = "Close readiness is a policy decision based on the verified run, open review items, and close blockers. The assistant can explain it but cannot approve the close."
            elif "settlement" in normalized:
                content = "A settlement is the merchant-facing record of money expected from a payment provider. ProofClose traces it to bank evidence and a versioned proof."
            else:
                content = "I can help with ProofClose operations, reconciliation, UTRs, integer paise, evidence, proofs, exceptions, and close readiness."
        return AssistantAnswer(
            status="ANSWERED",
            route="GENERAL_HELP",
            question=question,
            narration_status=narration_status,
            provider=self.provider_status(),
            message=content,
            answer_mode="GENERAL_HELP",
            answer_label=ANSWER_LABELS["GENERAL_HELP"],
            canonical={},
            citations={"proof_ids": [], "source_rows": [], "support_scope": "DIRECT"},
            detail="This is domain guidance, not a statement about the active run.",
            technical_details={"route": "GENERAL_HELP", "provider_status": self.provider_status().model_dump(mode="json")},
        ).model_dump(mode="json")

    def _record_provider_call(
        self,
        tenant_id: str,
        run_id: str,
        phase: str,
        *,
        result=None,
        failure=None,
        failure_category: str | None = None,
    ) -> None:
        if self.observability is None:
            return
        self.observability.assistant_call(
            tenant_id,
            run_id,
            phase=phase,
            status="failed" if failure else "succeeded",
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
            latency_ms=result.latency_ms if result else 0,
            model=result.model if result else self.provider_status().model,
            failure_category=failure_category or (failure.category if failure else None),
        )

    @staticmethod
    def _rescope_selection(selection, context: AssistantContext) -> Any:
        """Rebuild planner output inside the server-owned tenant/run scope."""
        if not isinstance(selection, ToolSelection):
            raise ValueError("planner selection is invalid")
        if selection.name == "REFUSE":
            if selection.arguments:
                raise ValueError("REFUSE arguments are not allowlisted")
            return selection.model_copy(update={"route": "REFUSE", "reason": "Provider refused outside approved evidence tools"})
        if selection.name not in ALLOWED_PROVIDER_TOOLS:
            raise ValueError("planner tool is not allowlisted")
        arguments = selection.arguments
        expected = TOOL_ARGUMENTS[selection.name]
        if set(arguments) != expected:
            raise ValueError("planner arguments are not allowlisted")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in arguments.items()):
            raise ValueError("planner arguments must be strings")
        scoped = dict(arguments)
        # The planner cannot choose the run. Selected IDs are also replaced
        # by trusted page context when one was supplied by the server.
        scoped["run_id"] = context.run_id
        if selection.name == "settlement_lookup" and context.settlement_id:
            scoped["settlement_id"] = context.settlement_id
        if selection.name in {"proof_explanation", "source_lineage"} and context.proof_id:
            scoped["proof_id"] = context.proof_id
        return ToolSelection(
            name=selection.name,
            arguments=scoped,
            route="PLANNER_TOOL",
            reason="Server-rescoped validated evidence tool",
        )

    def answer(
        self,
        tenant_id: str,
        run_id: str,
        question: str,
        *,
        settlement_id: str | None = None,
        proof_id: str | None = None,
        page: str | None = None,
        history: list[dict] | tuple[ConversationTurn, ...] | None = None,
    ) -> dict:
        question = self._validate_question(question)
        context = AssistantContext(run_id=run_id, settlement_id=settlement_id, proof_id=proof_id, page=page)
        intent = classify_copilot_intent(question, context)
        if intent.mode == "GENERAL_HELP":
            return self._general_help(tenant_id, run_id, question, self._history(history))
        if intent.mode == "UNABLE_TO_VERIFY":
            return AssistantAnswer(
                status="REFUSED",
                route="REFUSE",
                question=question,
                narration_status="not_requested",
                provider=self.provider_status(),
                message="I can help with ProofClose operations, but I cannot verify or perform that request.",
                answer_mode="UNABLE_TO_VERIFY",
                answer_label=ANSWER_LABELS["UNABLE_TO_VERIFY"],
                detail="The assistant is read-only and does not forecast, expose raw source data, or change settlement state.",
                technical_details={"route": "REFUSE", "reason": intent.reason},
            ).model_dump(mode="json")
        if intent.mode == "EVIDENCE_GUIDANCE" and not (settlement_id or proof_id):
            actions = guidance_for({})
            return AssistantAnswer(
                status="ANSWERED",
                route="GUIDANCE",
                question=question,
                narration_status="not_requested",
                provider=self.provider_status(),
                message="Select a settlement or exception and I’ll read its current evidence before suggesting next steps.",
                answer_mode="EVIDENCE_GUIDANCE",
                answer_label=ANSWER_LABELS["EVIDENCE_GUIDANCE"],
                detail="No settlement, proof, review, or close state was changed.",
                recommended_actions=actions,
                technical_details={"route": "GUIDANCE", "reason": intent.reason},
            ).model_dump(mode="json")
        selection = route_question(question, context)
        planner_used = False
        if selection.name == "REFUSE":
            if self.provider is None:
                return AssistantAnswer(
                    status="REFUSED",
                    route="REFUSE",
                    question=question,
                    narration_status="not_available",
                    provider=self.provider_status(),
                    message=(
                        "Evidence mode could not map that question to an approved tool. "
                        "Ask about unresolved money, close blockers, pending settlements, exceptions, a selected settlement, or a proof."
                    ),
                    answer_mode="UNABLE_TO_VERIFY",
                    answer_label=ANSWER_LABELS["UNABLE_TO_VERIFY"],
                    technical_details={"route": "REFUSE", "reason": "No verified tool was selected"},
                ).model_dump(mode="json")
            try:
                selection, planning_usage = self.provider.plan(
                    question,
                    context,
                    ALLOWED_PROVIDER_TOOLS,
                    attempt_guard=lambda: self.budget.consume(tenant_id, run_id),
                )
            except ProviderFailure as failure:
                if failure.category != "provider_budget_exhausted" or failure.result is not None:
                    self._record_provider_call(
                        tenant_id,
                        run_id,
                        "planning",
                        result=failure.result,
                        failure=failure,
                        failure_category=failure.attempt_category,
                    )
                return AssistantAnswer(
                    status="REFUSED",
                    route="REFUSE",
                    question=question,
                    narration_status=(
                        "provider_budget_exhausted"
                        if failure.category == "provider_budget_exhausted"
                        else "provider_unavailable"
                    ),
                    provider=self.provider_status(),
                    message="The configured AI planner was unavailable or unsafe. Deterministic evidence remains unchanged.",
                    answer_mode="UNABLE_TO_VERIFY",
                    answer_label=ANSWER_LABELS["UNABLE_TO_VERIFY"],
                    technical_details={"route": "REFUSE", "reason": "Provider planner unavailable"},
                ).model_dump(mode="json")
            except (TypeError, ValueError):
                return AssistantAnswer(
                    status="REFUSED",
                    route="REFUSE",
                    question=question,
                    narration_status="provider_unavailable",
                    provider=self.provider_status(),
                    message="The configured AI planner was unavailable or unsafe. Deterministic evidence remains unchanged.",
                    answer_mode="UNABLE_TO_VERIFY",
                    answer_label=ANSWER_LABELS["UNABLE_TO_VERIFY"],
                    technical_details={"route": "REFUSE", "reason": "Provider planner output invalid"},
                ).model_dump(mode="json")
            try:
                selection = self._rescope_selection(selection, context)
                self._record_provider_call(tenant_id, run_id, "planning", result=planning_usage)
                planner_used = True
            except (TypeError, ValueError):
                return AssistantAnswer(
                    status="REFUSED",
                    route="REFUSE",
                    question=question,
                    narration_status="provider_unavailable",
                    provider=self.provider_status(),
                    message="The configured AI planner was unavailable or unsafe. Deterministic evidence remains unchanged.",
                    answer_mode="UNABLE_TO_VERIFY",
                    answer_label=ANSWER_LABELS["UNABLE_TO_VERIFY"],
                    detail="No verified canonical result was available for this request.",
                    technical_details={"route": "REFUSE", "reason": "Planner selection could not be scoped"},
                ).model_dump(mode="json")

        if selection.name == "REFUSE":
            return AssistantAnswer(
                status="REFUSED",
                route="REFUSE",
                question=question,
                narration_status="not_requested",
                provider=self.provider_status(),
                message=(
                    "The AI planner kept this question outside the approved evidence tools. "
                    "No finance tool ran and deterministic evidence remains unchanged."
                ),
                answer_mode="UNABLE_TO_VERIFY",
                answer_label=ANSWER_LABELS["UNABLE_TO_VERIFY"],
                technical_details={"route": "REFUSE", "reason": "Provider refused"},
            ).model_dump(mode="json")

        try:
            # Direct routes are produced by server code; planner routes have
            # already been rebuilt above. FinanceTools still enforces the
            # final tenant/run and proof linkage checks.
            result = self.tools.execute(tenant_id, selection)
            canonical = result["facts"]
        except (KeyError, TypeError, ValueError, RuntimeError):
            return AssistantAnswer(
                status="REFUSED",
                route="REFUSE",
                tool_name=selection.name,
                question=question,
                narration_status="tool_scope_refused",
                provider=self.provider_status(),
                message="The selected evidence was not found inside the current tenant and run scope.",
                answer_mode="UNABLE_TO_VERIFY",
                answer_label=ANSWER_LABELS["UNABLE_TO_VERIFY"],
                technical_details={"route": "REFUSE", "reason": "Tool scope refused"},
            ).model_dump(mode="json")

        narration: str | None = None
        narration_status = "not_requested"
        unsupported_count = 0
        if planner_used and self.provider is not None:
            try:
                narrated = self.provider.narrate(
                    question,
                    selection.name,
                    canonical,
                    attempt_guard=lambda: self.budget.consume(tenant_id, run_id),
                )
                self._record_provider_call(tenant_id, run_id, "narration", result=narrated)
                validation = validate_narration(canonical, narrated.content)
                unsupported_count = validation.unsupported_claim_count
                if validation.accepted:
                    narration = narrated.content
                    narration_status = "accepted"
                else:
                    narration_status = "rejected_unsupported_claims"
            except ProviderFailure as failure:
                if failure.category != "provider_budget_exhausted" or failure.result is not None:
                    self._record_provider_call(
                        tenant_id,
                        run_id,
                        "narration",
                        result=failure.result,
                        failure=failure,
                        failure_category=failure.attempt_category,
                    )
                narration_status = (
                    "provider_budget_exhausted"
                    if failure.category == "provider_budget_exhausted"
                    else "provider_unavailable"
                )

        citations = result.get("citations", {"proof_ids": [], "source_rows": [], "support_scope": "DIRECT"})

        answer_mode = "EVIDENCE_GUIDANCE" if intent.mode == "EVIDENCE_GUIDANCE" else "CURRENT_FACT"
        canonical_message = _deterministic_message(selection.name, canonical)
        guidance_detail = "No settlement, proof, review, or close state was changed."
        return AssistantAnswer(
            status="ANSWERED",
            route="PLANNER_TOOL" if planner_used else "DIRECT_TOOL",
            tool_name=selection.name,
            question=question,
            canonical=canonical,
            narration=narration,
            narration_status=narration_status,
            explained_paise=canonical.get("explained_paise"),
            unresolved_paise=canonical.get("unresolved_paise"),
            lines=_report_lines(result["lines"]),
            proof_ids=result["proof_ids"],
            citations=citations,
            supporting_record_count=result["supporting_record_count"],
            run_record_count=result["run_record_count"],
            calculation_count=result["calculation_count"],
            unsupported_factual_claims=unsupported_count,
            provider=self.provider_status(),
            estimated_cost="unavailable",
            message=canonical_message,
            answer_mode=answer_mode,
            answer_label=ANSWER_LABELS[answer_mode],
            detail=guidance_detail if answer_mode == "EVIDENCE_GUIDANCE" else None,
            recommended_actions=guidance_for(canonical) if answer_mode == "EVIDENCE_GUIDANCE" else (),
            technical_details={
                "route": "PLANNER_TOOL" if planner_used else "DIRECT_TOOL",
                "tool_name": selection.name,
                "provider_status": self.provider_status().model_dump(mode="json"),
            },
        ).model_dump(mode="json")
