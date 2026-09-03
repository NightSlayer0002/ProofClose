# Architecture

## The vertical slice

```text
CSV evidence
    -> validation and raw hashes
    -> canonical rows plus field provenance
    -> immutable source snapshot
    -> deterministic Level 0/1/2 rules
    -> versioned Proof Objects
    -> exceptions / investigation / close policy
```

This ordering is deliberate. Workflow features consume proofs; they do not invent financial facts independently.

## Boundaries

| Module | Owns | Must not own |
|---|---|---|
| domain | typed money and records | persistence or HTTP |
| ingestion | byte/row limits, CSV parsing, hashes, idempotency | reconciliation |
| normalization | source-specific canonical mapping and provenance | guesses for unknown required fields |
| reconciliation | pure order, ledger, and bank rules | UI or model calls |
| proofs | immutable decision artifacts and rule dispatch | silent historical fallback |
| investigations | typed hybrid routing, isolated general help, fresh read-only facts, and guidance playbooks | authoritative arithmetic or writes |
| review / close | human state transitions and policy | autonomous approval |
| observability | sanitized timings and run events | authoritative finance state |

Product state lives in `proofclose.db`; sanitized measurements live in `observability.db`. Separating the stores prevents diagnostics concerns from becoming a back door into financial state.

## Reconciliation levels

- Level 0 groups payment rows by merchant order. Multiple attempts are allowed; settled credits exceeding a non-partial order create `UNEXPECTED_MULTIPLE_SETTLED_PAYMENTS`.
- Level 1 computes `sum(credits) - sum(debits)` for each settlement. A disagreement with the settlement entity creates `SETTLEMENT_LEDGER_MISMATCH`.
- Level 2 compares the reconstructed settlement with bank credits. Exact UTR and amount are necessary but not sufficient: exactly one candidate and a consistent ledger are required for `AUTO_VERIFIED`.

No-match decisions distinguish a legitimate pending window from a missing bank credit. Multiple credible candidates produce `AMBIGUOUS_MATCH` and `REFUSED`.

## Proof lifecycle

A Proof Object binds the decision to tenant, run, snapshot, input hashes, named evidence, formula, expected/observed/delta amounts, rule version, configuration version, and a stable fingerprint.

Historical reproduction resolves exactly `(rule_name, original_rule_version)`. Missing code is a failure, not permission to use current code. Current-rule re-evaluation applies the active rule to the same old inputs and writes a new proof whose `supersedes_proof_id` points to the original.

## Hybrid Evidence Copilot

The assistant separates language ability from financial authority:

```text
question
  -> typed intent and scope
  -> general concept? -> bounded general help with no current/source data
  -> current fact?    -> relevant allowlisted tool called now
  -> next step?       -> verified facts plus server-owned guidance
  -> unsafe/unknown?  -> explicit unable-to-verify response
```

Current amounts, counts, statuses, IDs, dates, rule versions, and configuration versions are privileged facts. They cannot come from chat history or model memory. A verified label requires a successful, relevant canonical tool result in the same request. Threads are keyed by run and selected context, so switching settlements changes both the visible divider and the conversation state without sending an AI request. The assistant remains read-only; workflow state belongs to review and close services.

## Scale path

The Buildathon build uses synchronous execution and SQLite for a zero-infrastructure offline demo. The module boundaries support a production migration to PostgreSQL, object storage for source bytes, a queue plus idempotent workers, and tenant-aware authorization without rewriting the pure rules. Partition by tenant/date, retain snapshot manifests, and keep versioned rule packages deployable for the required audit retention period.
