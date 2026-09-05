# Limitations

ProofClose is a production-oriented Buildathon slice, not a production deployment.

- The bundled examples are synthetic; custom INR CSVs are accepted through the same validator. Exact supported headers/units are required, with one file per source role in each run. See [Input contract](docs/INPUT_CONTRACT.md). One upload is limited to 5 MiB and 5,000 rows. There is no automatic column mapper, live Razorpay/bank connector, webhook verification, pagination, or credential lifecycle.
- SQLite and synchronous runs make the demo portable; the checked demo contains 267 rows and is not a throughput claim for high-volume concurrent merchants.
- Demo identity is intentionally insecure context. Production authentication and RBAC are not implemented.
- The rule set covers five high-value exception classes, not every refund, dispute, reversal, partial-settlement, timezone, FX, tax, or chargeback edge case.
- The optional NVIDIA integration adds natural general explanations and bounded read-only selection. Current financial facts still come only from deterministic tools. Provider configuration is not represented as successful reachability, and the 13-case offline assistant evaluation is boundary regression evidence, not a claim of broad language quality.
- Assistant token usage is measured, but estimated cost remains `unavailable` because this build has no versioned pricing configuration. ProofClose does not invent a price.
- OCR and vision are not authoritative inputs. Adding them safely requires immutable document bytes, page/region provenance, model/version metadata, confidence/refusal handling, quarantine, and human confirmation.
- Historical proof reproduction depends on retaining versioned rule code. If code is missing, the system correctly fails, but production needs an artifact retention and compatibility policy.
- Evaluation uses three deterministic seeds and small synthetic scenarios. Perfect precision/recall there is regression evidence, not a claim about unseen merchant data.
- The close pack is a hash-bound JSON manifest, not a cryptographic organizational signature or accounting-system posting. A hash detects changes against a trusted copy; it does not prove the uploader's authenticity or defeat an attacker who controls every stored copy.
- Source completeness is not proven: missing transactions inside a valid export, orphan bank credits, cross-period roll-forward and full general-ledger balancing are not comprehensively reconciled. A clean close applies only to the selected source scope and supported rules.
- Resolution briefs are versioned read-only guidance, not diagnosed root causes or signed proofs. Current-data narration remains bounded block selection, not unrestricted LLM reasoning; natural paraphrase coverage and live-provider quality still need broader evaluation.
- Database encryption, backups, disaster recovery, SSO, audit retention, malware scanning, rate limiting, multi-process job recovery, and external security review remain production work.

These limits are visible because trust improves when the system says what it cannot prove.
