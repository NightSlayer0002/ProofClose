from dataclasses import dataclass
from hashlib import sha256
import json
import re

from sqlalchemy import select

from app.ingestion.csv_parser import parse_csv
from app.ingestion.security import UploadLimits, UploadValidationError, validate_upload
from app.normalization.adapters import (
    NORMALIZATION_VERSION,
    FieldValidationError,
    SchemaMappingError,
    normalize_row,
    validate_headers,
    validate_normalized_row,
)
from app.storage.database import DatabaseManager
from app.storage.repositories import SourceRepository
from app.storage.schema import NormalizedRecord, RawRecord, SourceRecord


@dataclass(frozen=True)
class IngestionResult:
    source_id: str
    state: str
    accepted_rows: int
    inserted_rows: int
    duplicate_rows: int
    error: str | None = None


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


_ROW_FIELD_ERROR = re.compile(r"^row \d+ field [a-z_]+:")


def safe_quarantine_error(source_type: str, error: Exception) -> str:
    """Preserve actionable parser context without exposing CSV content."""
    message = str(error)
    if _ROW_FIELD_ERROR.match(message):
        return f"source {source_type} {message}"
    if "UTF-8" in message:
        field = "encoding"
    elif "no data rows" in message:
        field = "dataset"
    elif "unsupported source type" in message:
        field = "source_type"
    else:
        field = "header"
    return f"source {source_type} row 1 field {field}: {message}"


class IngestionService:
    def __init__(
        self,
        database: DatabaseManager,
        sources: SourceRepository,
        limits: UploadLimits | None = None,
    ) -> None:
        self.database = database
        self.sources = sources
        self.limits = limits or UploadLimits()

    def ingest_csv(
        self, tenant_id: str, source_type: str, filename: str, content: bytes
    ) -> IngestionResult:
        upload = validate_upload(filename, content, self.limits)
        source_id = f"src_{sha256(f'{tenant_id}:{source_type}:{upload.content_hash}'.encode()).hexdigest()[:20]}"
        with self.database.session() as session:
            existing = session.scalar(
                select(SourceRecord).where(
                    SourceRecord.tenant_id == tenant_id,
                    SourceRecord.source_type == source_type,
                    SourceRecord.content_hash == upload.content_hash,
                )
            )
            if existing is not None:
                return IngestionResult(existing.id, existing.state, 0, 0, existing.row_count, existing.error)

        try:
            parsed = parse_csv(upload.content, self.limits)
            validate_headers(source_type, parsed.headers)
            normalized_rows = []
            seen_external_ids: set[str] = set()
            for row_number, row in parsed.numbered_rows:
                try:
                    external_id, payload, origins = normalize_row(source_type, row)
                    validate_normalized_row(source_type, external_id, payload)
                    if external_id in seen_external_ids:
                        raise FieldValidationError("external_id", "duplicate external ID")
                    seen_external_ids.add(external_id)
                    normalized_rows.append((row, external_id, payload, origins))
                except FieldValidationError as exc:
                    raise ValueError(f"row {row_number} field {exc.field}: {exc}") from exc
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"row {row_number} field record: invalid canonical value") from exc
        except (UploadValidationError, SchemaMappingError, ValueError) as exc:
            safe_error = safe_quarantine_error(source_type, exc)
            with self.database.session() as session:
                session.add(
                    SourceRecord(
                        id=source_id,
                        tenant_id=tenant_id,
                        source_type=source_type,
                        filename=upload.filename,
                        content_hash=upload.content_hash,
                        state="QUARANTINED",
                        row_count=0,
                        error=safe_error,
                    )
                )
            return IngestionResult(source_id, "QUARANTINED", 0, 0, 0, safe_error)

        inserted = 0
        duplicates = 0
        with self.database.session() as session:
            source = SourceRecord(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                filename=upload.filename,
                content_hash=upload.content_hash,
                state="ACCEPTED",
                row_count=len(parsed.numbered_rows),
            )
            session.add(source)
            session.flush()
            for row, external_id, payload, origins in normalized_rows:
                raw_json = canonical_json(row)
                row_hash = sha256(raw_json.encode("utf-8")).hexdigest()
                existing_raw = session.scalar(
                    select(RawRecord).where(
                        RawRecord.tenant_id == tenant_id,
                        RawRecord.source_id == source_id,
                        RawRecord.source_type == source_type,
                        RawRecord.external_id == external_id,
                        RawRecord.content_hash == row_hash,
                    )
                )
                if existing_raw is not None:
                    duplicates += 1
                    continue
                raw_id = f"raw_{sha256(f'{tenant_id}:{source_id}:{source_type}:{external_id}:{row_hash}'.encode()).hexdigest()[:24]}"
                session.add(
                    RawRecord(
                        id=raw_id,
                        tenant_id=tenant_id,
                        source_id=source_id,
                        source_type=source_type,
                        external_id=external_id,
                        content_hash=row_hash,
                        payload_json=raw_json,
                    )
                )
                session.flush()
                provenance = {
                    field: {
                        "tenant_id": tenant_id,
                        "source_id": source_id,
                        "raw_record_id": raw_id,
                        "raw_field": raw_field,
                        "raw_value": row.get(raw_field, ""),
                        "normalized_value": normalized_value,
                        "normalization_version": NORMALIZATION_VERSION,
                    }
                    for field, (raw_field, normalized_value) in origins.items()
                }
                session.add(
                    NormalizedRecord(
                        id=f"norm_{sha256(f'{raw_id}:{NORMALIZATION_VERSION}'.encode()).hexdigest()[:24]}",
                        tenant_id=tenant_id,
                        source_id=source_id,
                        raw_record_id=raw_id,
                        record_type=source_type,
                        normalization_version=NORMALIZATION_VERSION,
                        payload_json=canonical_json(payload),
                        provenance_json=canonical_json(provenance),
                    )
                )
                inserted += 1
        return IngestionResult(source_id, "ACCEPTED", len(parsed.numbered_rows), inserted, duplicates)
