# Failure Modes

| Failure | Safe behavior | Operator signal |
|---|---|---|
| Invalid or oversized CSV | Reject or quarantine; create no valid empty source | upload error with a stable code |
| Unknown required schema | Abstain from normalization | `SCHEMA_MAPPING_REQUIRED` |
| Duplicate ingestion | Reuse idempotent identity; do not duplicate money | duplicate-row count |
| Settlement ledger disagreement | Do not bank-match as verified | `SETTLEMENT_LEDGER_MISMATCH` |
| Two exact UTR/amount bank rows | Refuse to choose | `AMBIGUOUS_MATCH`, candidate count 2 |
| Missing bank row inside pending window | Wait without accusing a miss | `PENDING` |
| Missing bank row after window | Surface unresolved money | `MISSING_BANK_CREDIT` |
| Original rule code missing | Do not use current code for history | `RULE_IMPLEMENTATION_UNAVAILABLE` |
| Proof fingerprint differs on reproduction | Preserve both fingerprints and distrust reproduction | proof reproducibility failure event |
| Optional AI unavailable | Keep reconciliation and current-fact tools working; use deterministic general explanations where supported | provider state plus honest fallback |
| General model invents current state | Reject output; current facts require a fresh relevant tool | `Unable to verify` or canonical fallback |
| Stale chat context | Key threads by run and selected object; history never supplies truth | visible context divider and fresh tool call |
| Assistant asked to approve/mutate | Refuse; expose no write tool | `Unable to verify` |
| Assistant receives source/prompt exfiltration request | Refuse before provider call | no raw/provider payload returned |
| Prompt text inside evidence | Treat as inert data | deterministic decision unchanged |
| Run/system error | Never auto-verify affected work; block close | `SYSTEM_ERROR` / failed run |
| New evidence arrives during run | Create a new source/snapshot/run | old run remains immutable |
