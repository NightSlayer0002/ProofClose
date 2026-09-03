# Evidence Provenance

Every accepted CSV row is stored as an immutable raw payload with a SHA-256 content hash. Normalization records the source, raw record, raw field/value, normalized value, and normalization version. A snapshot freezes the ordered source versions used by a run and has its own hash.

A decision is therefore traceable as:

```text
displayed amount -> proof input -> normalized field -> raw record -> source hash -> snapshot
```

Corrections create new source versions and new snapshots. They never edit an old proof's evidence. The bundled demo uses the same ingestion and normalization services as an uploaded CSV, so it cannot bypass provenance by inserting expected decisions.

Assistant conversation is not provenance. A current financial answer cites the canonical record or proof returned by a read-only tool during that request. General guidance may have no source footer because it is education, not a statement about the current ledger. Recommended actions are linked to the verified exception condition but remain instructions for a human; they do not mutate evidence or review state.
