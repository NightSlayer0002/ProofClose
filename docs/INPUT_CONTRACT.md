# Bring your own reconciliation data

Open **Data sources** (or `/workspace/sources`) to upload and validate CSVs. Select one accepted delivery per role, then create a snapshot and reconcile. Uploading a file does not alter an earlier run. No existing or demo file is automatically selected on this screen.

This is an explicit INR settlement contract, not a universal bank-file parser. New identifiers, amounts and dates do not need code changes. Different columns, units or financial meanings do need an adapter. Never silently treat a rupee amount as paise or a gross payment as a net bank credit.

## Exact source roles

| Role | Required columns | Meaning |
| --- | --- | --- |
| `merchant_orders` | `order_id, amount_paise, amount_paid_paise, status, partial_payment` | Merchant's order/payment expectation |
| `razorpay_recon` | `entity_id, type, debit, credit, amount, settlement_id, settlement_utr` | Payment/refund ledger; net credit is credit minus debit |
| `settlements` | `id, amount, status, utr, created_at` | Provider's settlement entity; `amount` is **paise** |
| `bank_statement` | `bank_ref, utr, credit_amount_paise, value_date, narration` | Bank-credit evidence, not a general debit/credit bank ledger |

The live schema at `GET /api/sources/schema` lists required/optional/money columns and is derived from the ingestion validator. The UI downloads required-column templates. Headers must match exactly. Unknown columns and duplicate headers are rejected. A blank template is not an example dataset.

All four roles must be represented when you run reconciliation. You can reuse previously accepted deliveries and replace only the changed role; the UI does not require four new uploads every time. Filenames are arbitrary. If a replacement upload fails, that role's old selection is cleared to prevent reconciling an unintended file; you may explicitly reselect the old accepted delivery.

“Paise fields” is a unit list, not another required-column list. For example, merchant `amount_due_paise` is optional even though it appears in the money-field list. The ledger's **linked template** includes optional `order_id` because order/payment checks need that relationship. Required-only ledger columns describe settlement reconciliation, not complete order attribution.

- All monetary fields, including `amount`, `credit`, `debit`, `fee`, `fees` and `tax`, are non-negative whole INR paise. ₹125.50 becomes `12550`. No comma separators, currency symbols, decimal amounts or guessed conversion.
- Recon `type`: `payment` or `refund`. Only one of credit/debit may be positive per row, and at least one must be positive.
- Settlement status: `created`, `pending`, `processed`, `failed`, `cancelled` or `reversed`. Orders: `created`, `attempted`, `paid`, `partially_paid` or `cancelled`.
- Booleans accept true/false, 1/0, yes/no or y/n, case-insensitively.
- Dates accept an ISO date, a timezone-aware ISO timestamp, or epoch seconds. Naive timestamps with a time but no timezone are rejected. A date-only field is interpreted at UTC midnight, which may require an explicit upstream bank-timezone adapter.
- Optional columns may be omitted; including a column does not mean every empty cell is valid. Use `0` for unused included monetary values and valid values for included status/boolean fields.
- Join recon `settlement_id` to settlement `id`. For order-level payment checks, include recon `order_id` matching the order file. Each source's external record IDs must be unique within that delivery.
- Use aligned reporting windows and complete ledger coverage. Merge same-role file parts upstream with duplicate-ID checks: a snapshot accepts at most one delivery for each role, not arbitrarily many statement files.
- Limits: 5 MiB and 5,000 rows per file. Invalid rows quarantine the delivery rather than partially accepting it. Quarantined sources cannot enter a snapshot.

## Evaluation time and history

Custom inputs default to the current server time. For a historical dataset, supply **Evaluate as of** in the UI or timezone-aware `evaluated_at` in `POST /api/runs`. It is normalized to UTC and bound into every proof. This clock affects timing/pending rules; it does not filter rows to a reporting period. Choose source files with the intended coverage yourself.

Only the exact bundled demo source contents get the frozen example clock automatically. Recognition uses all four source content hashes. Changing any delivery removes that default; matching itself never branches on demo identifiers. The evaluation harness passes its fixture clock explicitly.

Historical proof reproduction uses the original rule and bound evaluation time. Creating a new run with a different time is a separate operation, not reproduction.

## Connecting live systems

An authorized adapter would fetch provider reports and bank exports/APIs, retain their original bytes, normalize to this contract, upload each delivery, select source IDs and start a run. The existing upload/snapshot/run APIs are application APIs, not integrations installed inside a bank.

Production work still includes provider-specific mappings, Decimal-based rupee conversion where required, verified webhook signatures, pagination, idempotent delivery keys, secrets management, consent and access controls. There is no live connector or automatic schema mapper in this POC. Keep adapter version, original-file hash and conversion manifest together; do not call a converted CSV the untouched bank original.

## Before handing us a new dataset

Confirm currency/units, timezone, reporting period, net-versus-gross semantics, identifier joins and expected exception types. Missing files fail explicitly. Missing or extra transactions inside otherwise valid files are not comprehensively detected: source completeness, orphan bank credits, split settlements, FX and full chargeback/reversal accounting remain limitations. A clean result proves the checks within the selected scope, not that the bank's entire ledger is complete.
