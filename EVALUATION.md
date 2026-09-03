# Evaluation

ProofClose has two deliberately separate offline evaluations: deterministic reconciliation/proof behavior and Hybrid Evidence Copilot boundaries. Neither scorecard calls NVIDIA, and neither imports labels into the application runtime.

## Deterministic reconciliation evaluation

`evals/runner.py` creates a fresh isolated database for each seed, generates synthetic source files, ingests them, freezes a snapshot, executes the current rules, and compares outputs with held-out scenario labels. The seeds change both amounts and the settlement IDs assigned to scenarios. Counts are summed across seeds before ratios are rounded.

The checked-in run uses seeds `20260831`, `20260901`, and `20260902`, processes 801 synthetic rows in total, and identifies itself as `deterministic_offline`.

This directly exercises the Buildathon finance-loop requirement with 267 source rows per seed—well above the 50-record minimum—while retaining the full exception list rather than showing one cherry-picked match.

| Metric | Definition | Checked-in result |
|---|---|---:|
| Auto-match precision | Correct automatic matches / all automatic matches | 1.000000 |
| Automation rate by settlement count | Automatically verified settlements / all settlements | 0.583333 |
| Money automation rate | Expected paise on automatic settlements / total expected paise | 0.570966 |
| Exception precision | Correct detected exceptions / detected exceptions | 1.000000 |
| Exception recall | Correct detected exceptions / expected exceptions | 1.000000 |
| Exception F1 | Harmonic mean of exception precision and recall | 1.000000 |
| Ambiguous abstention recall | Correct refusals on ambiguous cases / ambiguous cases | 1.000000 |
| False refusal count | Refusals not required by the ground truth | 0 |
| Unique allocation violation count | Duplicate automatic bank allocation or automatic result without exactly one candidate | 0 |
| Proof coverage | Required settlement/order subjects with a proof / all required subjects | 1.000000 |
| Proof subject accuracy | Proofs bound to the expected subject / proofs checked | 1.000000 |
| Historical reproduction success rate | Successfully reproduced proofs / proofs whose implementation is available | 1.000000 |
| Tamper detection rate | Detected proof mutations / mutation probes | 1.000000 |

The benchmark also records an explicit unavailable-version probe. Removing the original registered rule for a proof must produce `RULE_IMPLEMENTATION_UNAVAILABLE`; it is not misreported as a successful reproduction. Additional allocation boundary cases—shared bank rows, UTR/amount/time mismatches, amount-only candidates, future/non-processable records, and currency problems—remain covered by the lower-level reconciliation suite and are named in the scenario manifest.

Generate the deterministic artifacts once with:

```powershell
.\.venv\Scripts\python.exe -m evals.runner --seeds 20260831 20260901 20260902 --output evals/results
```

## Hybrid Evidence Copilot evaluation

`evals/assistant_runner.py` executes 13 checked-in synthetic questions through the real typed router and response renderer with scripted read-only finance tools. It covers greetings, UTR and integer-paise explanations, current amounts, paraphrases, selected-settlement facts, evidence-backed guidance, forecast refusal, source-data exfiltration, tool injection, and mutation requests.

| Metric | Checked-in offline result |
|---|---:|
| Tool-selection accuracy | 1.000000 |
| Grounded-answer accuracy | 1.000000 |
| Guidance-action suitability | 1.000000 |
| False-refusal rate | 0.000000 |
| Adversarial-refusal rate | 1.000000 |
| Unsupported-claim count | 0 |
| Provider latency p50/p95 | unavailable |

Offline latency is the string `unavailable`, never numeric zero, because no provider call occurs. Unsupported claims are summed from actual response validation fields rather than hard-coded into the report.

Generate the assistant artifacts once with:

```powershell
.\.venv\Scripts\python.exe -m evals.assistant_runner --mode offline --output evals/results
```

An opt-in live evaluation is available only through `run_assistant_evaluation` with an initialized application. It accepts only the checked-in synthetic questions, sets provider retries to zero, and stops before its explicit provider-call cap. Live p50/p95 use nearest-rank percentiles over successful calls only; when no call succeeds, accuracy and latency must be reported as `unavailable`. Live mode is intentionally excluded from the fixed offline pass and from the checked-in claims.

## Outputs and limits

- `evals/results/evaluation_results.json`: multi-seed manifest, additive counts, metrics, per-seed predictions, proof reproduction, and tamper probes.
- `evals/results/evaluation_results.csv`: deterministic metric table.
- `evals/results/eval_manifest.json`: dataset, source, rule `2.0`, configuration `2.0`, Proof Object `proof-object/v2`, Close Pack `proofclose-close-pack/v2`, seeds, Git commit, and offline mode.
- `evals/results/assistant_evaluation_results.json`: assistant cases, boundary scores, and an explicit zero-call offline provider manifest.
- `evals/results/assistant_evaluation_results.csv`: compact assistant metric table.

These are small, synthetic POC evaluations. They demonstrate deterministic behavior, grounding boundaries, and reproducibility on known scenarios; they do not establish production-scale accuracy, provider quality, real-bank coverage, or live latency.
