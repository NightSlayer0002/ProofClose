# Security

## Identity boundary

`INSECURE_DEMO_CONTEXT` is an explicit warning, not an authentication claim. Demo headers only select the fixed local actor/tenant accepted by `backend/app/api/context.py`. In non-demo mode the middleware rejects these headers with `PRODUCTION_AUTH_REQUIRED`. Production requires an identity provider, signed tokens, role claims, and backend authorization on every write.

## Data controls

- Tenant ID is required by public repository operations and cross-tenant lookups return no object.
- Uploads enforce safe filenames, `.csv`, allowed MIME types, UTF-8, byte/row limits, known source types, and required headers.
- Path traversal filenames are rejected.
- Raw records and snapshots are content-hashed; duplicates are idempotent.
- Authoritative amounts never use binary floating point.
- CSV cells starting with spreadsheet-control characters are escaped on export.
- Product and observability databases are separated; raw finance payloads do not enter diagnostics.

## AI boundary

Uploaded narration may contain instructions such as “ignore previous rules.” It remains untrusted evidence text. Deterministic functions alone compute amounts and decisions. The Hybrid Evidence Copilot may use natural prose for general education, but current financial claims require a fresh relevant allowlisted read-only tool. It cannot review, challenge, approve close, write SQL, mutate records, or move money.

The browser receives canonical facts, guidance, citations, and technical metadata as separate fields. Conversation history is bounded and sanitized and may influence phrasing only. Raw source/bank narration, current amounts or statuses, credentials, provider bodies, hidden instructions, and tool internals cannot enter the general-help provider path. Unsafe questions or output use deterministic refusal/fallback. For evidence answers, model-selected facts must already exist in the relevant tool result; unsupported additions are counted and discarded. Provider failures expose sanitized categories rather than response bodies.

## Secret handling

Secrets are read from environment variables and local runtime files are ignored by Git. The local Evidence Assistant needs only `NVIDIA_API_KEY`; unrelated OAuth, OCR, and vision credentials are not part of this product. Health and diagnostics report configuration/reachability without returning credentials. Run:

```powershell
.\.venv\Scripts\python.exe scripts\scan_secrets.py
```

The scanner is a safety net, not a replacement for GitHub secret scanning, dependency alerts, key rotation, audit-log monitoring, and a real secrets manager.

## Threats still requiring production work

See `LIMITATIONS.md`: authenticated identity, authorization roles, CSRF policy, rate limiting, malware scanning, encryption/key management, backups, retention/deletion, dependency monitoring, and independent penetration testing are not represented as complete.
