# From a failed check to an evidence request

The resolution brief is a read-only handoff for an operator investigating a discrepancy. Select a settlement, ask **What should I do next?**, expand **Evidence to request**, and download the brief. Proof links remain below the answer.

It contains:

- the recorded decision and expected amount from the verified result;
- requests derived from failed evidence predicates (reference, amount, ledger, timing or competing candidates);
- an explicit statement of uncertainty: unmatched money is not automatically a loss;
- conditions for importing new evidence and re-running checks, without promising that a single document guarantees auto-verification;
- the original proof references and `resolution-brief/v1` guidance version.

For example, two exact UTR-and-amount candidates lead to a request for transaction-level evidence that distinguishes them. The assistant does not choose one or recommend changing an amount to force a match. An order finding asks for order/payment evidence rather than describing it as a bank match. Auto-verified settlements do not get an unnecessary exception-review playbook.

## What AI contributes

Concept explanations can use bounded general model prose with no current/raw financial records. Current questions use a relevant tenant/run-scoped read-only tool. Common questions route deterministically; unfamiliar paraphrases may use the model planner.

For applicable evidence questions, NVIDIA can select and order up to three server-authored explanation blocks. Only blocks appropriate to the verified result are offered. The server validates the complete selection and renders it; unknown blocks, extra claims or malformed output cause fallback. The model cannot add a made-up cause or monetary figure. The earlier scalar fact-key narrator remains a fallback for tools without a resolution catalog.

This is deliberately narrower than unrestricted chatbot reasoning. It improves emphasis and accessibility, not the financial decision. The brief and recommendations also work offline. It is not an autonomous agent, a semantic guarantee against every jailbreak, an externally sent bank request, or a signed audit artifact. The downloaded TXT is editable; the linked original Proof Object is the tamper-evident record.

The default process-local allowance is 20 provider attempts per tenant/run, including retries; override `PROOFCLOSE_PROVIDER_CALL_BUDGET` to 0–100. Exhaustion is visible and falls back to built-in explanations. This is a local spend guard, not durable billing enforcement or production rate limiting. Usage is measured; cost is unavailable without versioned pricing. Mock-provider tests do not demonstrate live reachability or general language accuracy.

## Product hypothesis, not a world-first claim

Our target workflow is a merchant operations team or accounting practice that must explain an unresolved settlement to somebody else and preserve why it reached a decision. The product hypothesis is that a proof-linked evidence request reduces repeated investigation and back-and-forth.

Matching and exception automation already exist in [BlackLine](https://www.blackline.com/products/financial-close/transaction-matching/) and [Duco](https://du.co/product/reconciliation/). ProofClose is not claiming to invent reconciliation or to outperform those systems. Its focused demonstration combines immutable evidence, historical rule reproduction, safe abstention and an actionable resolution handoff. Validate value with real operators: time to gather missing evidence, clarification rounds per case, reopened cases and false automatic matches—not chatbot verbosity or an invented ROI.
