import re

from app.investigations.contracts import AssistantContext, CopilotIntent, ToolSelection


_GENERAL_PATTERNS = (
    "hi", "hello", "hey", "what is a utr", "what's a utr", "why does proofclose",
    "why use integer paise", "what are paise", "what can you help", "how does proofclose work",
    "what is reconciliation", "what is a proof", "what is an exception", "how do i use proofclose",
    "what are proofs", "explain proof", "explain proofs", "what are exceptions", "explain exception", "explain exceptions",
    "what does reconciliation mean", "explain reconciliation", "what is close readiness", "what is close state",
    "explain close", "explain settlement reconciliation", "what are settlements",
)
_CURRENT_PATTERNS = (
    "unresolved", "missing", "blocked", "blocker", "exception", "pending", "status", "amount",
    "money", "settlement", "proof", "utr", "close", "today", "current", "changed", "rule", "version",
)
_UNSAFE_PATTERNS = (
    "forecast", "predict", "charge back next", "next month", "next year", "will customer",
    "raw narration", "raw bank", "show secret", "api key", "ignore previous", "system prompt",
    "bank narration", "raw source", "source rows", "source data", "evidence rows", "raw records", "all source", "show all records", "evidence json", "canonical json",
    "developer message", "hidden instruction", "hidden prompt", "tool schema", "tool instructions", "internal instructions", "show the prompt", "reveal prompt", "route enum", "direct_tool", "planner_tool", "chain of thought", "exfiltrate",
    "delete", "reset", "upload", "reject this", "approve this settlement", "change the decision",
)


def is_review_choice_question(question: str) -> bool:
    """A request for decision criteria, never permission to perform a review."""
    normalized = " ".join(question.lower().split())
    return bool(re.match(r"^(?:so[, ]+)?(?:should|can|may|do|would) i\b", normalized)
                and re.search(r"\b(?:accept|reject|approve|leave|mark)\b", normalized))


def classify_copilot_intent(question: str, context: AssistantContext) -> CopilotIntent:
    normalized = " ".join(question.lower().split())
    # Explain the ingestion workflow without giving the assistant a write tool.
    if normalized.startswith(("how do i upload", "how can i upload", "how to upload", "what csv format", "how do i import")) and not any(signal in normalized for signal in ("secret", "prompt", "ignore", "raw", "source data")):
        return CopilotIntent(mode="GENERAL_HELP", reason="The user asks for input-format instructions, not an upload action")
    review_choice = is_review_choice_question(question)
    unsafe_matches = [pattern for pattern in _UNSAFE_PATTERNS if pattern in normalized]
    if unsafe_matches:
        # A question phrased as a policy check remains useful guidance; an
        # imperative approval request is an attempted state mutation.
        if review_choice and all(pattern in {"reject this", "approve this settlement"} for pattern in unsafe_matches):
            return CopilotIntent(mode="EVIDENCE_GUIDANCE", reason="Approval policy can be explained without changing state")
        return CopilotIntent(mode="UNABLE_TO_VERIFY", reason="The request is outside the read-only evidence boundary")
    # A conceptual question is general help only until it explicitly binds
    # itself to the active run or selected evidence. Mixed questions are
    # evidence-first so the model cannot answer from language alone.
    has_live_binding = any(
        phrase in normalized
        for phrase in ("this settlement", "this run", "current run", "selected settlement", "active run", "relate to this")
    )
    if review_choice or any(signal in normalized for signal in ("what should i do", "what do i do", "next step", "can i approve", "may i approve", "should i approve")):
        return CopilotIntent(mode="EVIDENCE_GUIDANCE", reason="The question asks for operational next steps")
    if has_live_binding and any(signal in normalized for signal in _CURRENT_PATTERNS):
        return CopilotIntent(mode="CURRENT_FACT", reason="The question binds a domain concept to selected current evidence")
    if normalized in _GENERAL_PATTERNS or any(normalized.startswith(pattern + " ") or normalized.startswith(pattern + "?") for pattern in _GENERAL_PATTERNS):
        return CopilotIntent(mode="GENERAL_HELP", reason="The question asks for domain or product guidance")
    if any(pattern in normalized for pattern in _CURRENT_PATTERNS) or context.settlement_id or context.proof_id:
        return CopilotIntent(mode="CURRENT_FACT", reason="The question may contain a current run or selected evidence fact")
    if normalized in {"thanks", "thank you", "good morning", "good afternoon", "good evening"}:
        return CopilotIntent(mode="GENERAL_HELP", reason="The question is conversational domain context")
    if any(word in normalized for word in ("how", "what", "why", "explain")):
        return CopilotIntent(mode="GENERAL_HELP", reason="The question asks for bounded domain explanation")
    return CopilotIntent(mode="UNABLE_TO_VERIFY", reason="The question is outside the supported ProofClose domain")


def route_question(question: str, context: AssistantContext | None = None) -> ToolSelection:
    normalized = " ".join(question.lower().split())
    active = context or AssistantContext(run_id="unselected")
    has_selected = bool(active.settlement_id or active.proof_id)
    run_summary_question = any(signal in normalized for signal in ("today", "close summary", "total unresolved", "run summary"))
    next_steps = is_review_choice_question(question) or any(signal in normalized for signal in ("what should i do", "what do i do", "next step", "can i approve", "should i approve", "may i approve", "recommend", "resolution brief"))
    if not has_selected and next_steps:
        return ToolSelection(name="close_blockers", arguments={"run_id": active.run_id})
    if has_selected and not run_summary_question and (next_steps or "this blocked" in normalized or "evidence is missing" in normalized):
        return ToolSelection(name="settlement_lookup", arguments={"run_id": active.run_id, "settlement_id": active.settlement_id}) if active.settlement_id else ToolSelection(name="proof_explanation", arguments={"run_id": active.run_id, "proof_id": active.proof_id})
    if (not has_selected or run_summary_question) and ("unresolved" in normalized or any(signal in normalized for signal in ("not auto-verified", "not auto verified", "close summary", "money is missing", "how much is missing", "has it changed", "current status", "how much unresolved", "total unresolved"))):
        return ToolSelection(name="close_summary", arguments={"run_id": active.run_id})
    if any(signal in normalized for signal in ("prevents today's close", "prevent today's close", "blocks close", "blocking exceptions", "how many blockers", "blocker count", "is this blocked", "why is this blocked")):
        return ToolSelection(name="close_blockers", arguments={"run_id": active.run_id})
    if any(signal in normalized for signal in ("break down exceptions", "exception breakdown", "exceptions by type", "how many exceptions", "exception count")):
        return ToolSelection(name="exception_breakdown", arguments={"run_id": active.run_id})
    if any(signal in normalized for signal in ("settlements are pending", "which settlements are pending", "pending settlements")):
        return ToolSelection(name="pending_settlements", arguments={"run_id": active.run_id})
    if active.proof_id and any(signal in normalized for signal in ("proof", "formula", "rule", "decision", "what should i do", "next step", "approve")):
        return ToolSelection(
            name="proof_explanation",
            arguments={"run_id": active.run_id, "proof_id": active.proof_id},
            reason="Selected proof supplies exact evidence context",
        )
    if active.proof_id and any(signal in normalized for signal in ("source", "lineage", "origin", "came from")):
        return ToolSelection(
            name="source_lineage",
            arguments={"run_id": active.run_id, "proof_id": active.proof_id},
            reason="Selected proof supplies exact lineage context",
        )
    if active.proof_id and any(signal in normalized for signal in ("tell me more", "explain it", "explain that", "what does that mean", "why did that happen")):
        return ToolSelection(name="proof_explanation", arguments={"run_id": active.run_id, "proof_id": active.proof_id})
    if active.settlement_id:
        return ToolSelection(
            name="settlement_lookup",
            arguments={"run_id": active.run_id, "settlement_id": active.settlement_id},
            reason="Selected settlement supplies exact evidence context",
        )
    if any(signal in normalized for signal in ("how does proofclose work", "how do i use", "what is proofclose", "help me use")):
        return ToolSelection(name="product_help", arguments={"run_id": active.run_id})
    return ToolSelection(
        name="REFUSE",
        arguments={"run_id": active.run_id},
        route="PLANNER_TOOL",
        reason="Question requires a validated allowlisted tool plan",
    )
