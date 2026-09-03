# Incident Response

## If a financial decision looks wrong

1. Stop close approval for the affected run; do not delete or edit evidence.
2. Record tenant, run, snapshot, proof, rule version, and proof fingerprint.
3. Use **Reproduce historical proof**. A missing versioned rule or fingerprint mismatch is a reproducibility incident.
4. Inspect source hashes and provenance. Compare with the original exported files outside the application.
5. If policy changed, use **Evaluate with current rules** to create a linked comparison. Never call that historical reproduction.
6. Challenge the match or leave the exception unresolved with a reason so the audit trail preserves human control.
7. Contain the affected rule version and runs; do not silently recalculate unrelated history.
8. Correct by releasing a new versioned rule, creating a new run, and documenting impact. Preserve the original artifact.

## If a credential may be exposed

Revoke and rotate it first, then remove access, inspect provider/Git/audit logs, identify affected environments, and notify the responsible owner. Rewriting Git history is not a substitute for revocation.

## If an assistant answer looks wrong or leaks context

1. Treat the answer as non-authoritative and stop using it for a close decision.
2. Record the run, selected context, visible answer mode, citations, and sanitized request identifier; do not copy secrets into the incident.
3. Compare every current claim with the canonical tool/proof result from the same run.
4. Disable the optional provider key if source text, hidden instructions, credentials, or cross-tenant data may have crossed the boundary.
5. Preserve the offending synthetic prompt and sanitized response for a regression fixture.
6. Fix routing or containment, add an adversarial case, and release deliberately. Never “train” directly from a user challenge.

## Evidence to retain

Source and snapshot hashes, Proof Objects, both reproduction fingerprints, versioned rule/configuration artifacts, exception reviews, close approvals, sanitized request/run IDs, and a timeline of containment and correction.
