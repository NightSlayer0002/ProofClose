# Design Decisions

## Evidence before automation

The product begins with immutable source evidence and deterministic proofs rather than an assistant chat. A finance user can use and audit the core workflow when every model is offline.

## Integer paise

Money crosses the domain boundary as whole paise. This prevents binary floating-point surprises and makes formulas/fingerprints reproducible.

## A match is a predicate, not a confidence vibe

Named evidence drives decisions. Exact UTR, exact amount, a consistent ledger, and one candidate are explicit requirements. Scores can help humans scan evidence but cannot override a failed predicate.

## Refusal is a successful outcome

Choosing between duplicate bank candidates would create a clean-looking but untrustworthy ledger. `REFUSED` preserves uncertainty and directs human review.

## Reproduction is not re-evaluation

Reproduction asks whether the original decision can be recreated with the original code. Re-evaluation asks what current code says about old evidence. Combining them would erase the meaning of audit history.

## Hybrid AI: free language, bounded facts

Models are good at language; they are not the system of record. General concepts can be explained conversationally without pretending they are evidence. Any current-run amount, count, status, identifier, date, rule, or configuration must be fetched through a relevant read-only tool during that request. Evidence guidance combines those verified facts with server-owned action playbooks. The model cannot calculate authoritative totals or perform workflow writes.

Conversation history is language context, not truth. The UI therefore stores separate threads per run/settlement context and makes a context switch visible before the next question.

## Exact lookup before embeddings

Structured finance identifiers belong in indexed relational columns. If supporting documents are added, SQLite/PostgreSQL full-text search is the first upgrade for exact UTR, settlement, and order references. Embeddings may help find conceptually related policy prose, but they should never authorize a transaction match. Semantic answers are not blindly cached because permissions, evidence, and current close state form part of the answer.

## Feedback does not self-train

A challenge creates an append-only feedback/audit record. It cannot change a rule, threshold, prompt, or model. Offline analysis, approval, a new version, tests, and measured rollout are required before feedback affects behavior.

## Risk work follows the real authority boundary

The implemented controls focus on tenant isolation, upload abuse, prompt injection, proof reproducibility, export injection, and unauthorized workflow writes. Generic model-risk features that do not affect this read-only optional model path are not added as theatre; limitations name the production controls that are genuinely missing.

## SQLite and synchronous runs for the demo

One-command portability makes the evidence path judgeable offline. Repositories and pure rules isolate the seams for PostgreSQL, object storage, and queued workers later.

## GreenMind influence without copying its visual personality

ProofClose borrows persistent navigation and contextual drill-down. It replaces chat-first presentation and decorative surfaces with a compact operations table, restrained colors, explicit labels, and an evidence drawer.
