from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.models import BankLine
from app.ingestion.csv_parser import parse_csv
from app.ingestion.security import UploadLimits, UploadValidationError, validate_upload
from app.ingestion.service import IngestionService
from app.normalization.adapters import SchemaMappingError, normalize_row
from app.storage.database import DatabaseManager
from app.storage.repositories import SourceRepository


@pytest.fixture
def ingestion(tmp_path: Path) -> IngestionService:
    database = DatabaseManager(f"sqlite:///{(tmp_path / 'proofclose.db').as_posix()}")
    database.create_schema()
    return IngestionService(database, SourceRepository(database))


def bank_csv(row: str) -> bytes:
    return (
        "bank_ref,utr,credit_amount_paise,value_date,narration\n"
        f"{row}\n"
    ).encode()


def test_upload_rejects_path_traversal() -> None:
    """An attacker-controlled path must never escape the upload boundary."""
    with pytest.raises(UploadValidationError, match="unsafe filename"):
        validate_upload("../../bank.csv", b"bank_ref,utr\nb1,U1\n", UploadLimits())


def test_upload_rejects_unsupported_extension() -> None:
    """Allowing active or unknown file types expands the parser attack surface."""
    with pytest.raises(UploadValidationError, match="CSV files"):
        validate_upload("bank.exe", b"MZ", UploadLimits())


def test_upload_rejects_oversized_content() -> None:
    """The size boundary must fail before parsing consumes unbounded resources."""
    with pytest.raises(UploadValidationError, match="exceeds"):
        validate_upload("bank.csv", b"123456", UploadLimits(max_bytes=5))


def test_valid_upload_returns_sanitized_name_and_hash() -> None:
    """A stable content hash is the evidence identity used for idempotency."""
    result = validate_upload("Bank Report.csv", b"bank_ref,utr\nb1,U1\n", UploadLimits())
    assert result.filename == "Bank_Report.csv"
    assert len(result.content_hash) == 64
    assert result.content == b"bank_ref,utr\nb1,U1\n"


def test_parsed_csv_retains_physical_row_numbers() -> None:
    """Dropping row positions would make a quarantined financial record untraceable."""
    parsed = parse_csv(bank_csv("b1,U1,100,2026-08-26,SETTLEMENT"), UploadLimits())

    assert parsed.headers == ["bank_ref", "utr", "credit_amount_paise", "value_date", "narration"]
    assert parsed.numbered_rows == [
        (2, {"bank_ref": "b1", "utr": "U1", "credit_amount_paise": "100", "value_date": "2026-08-26", "narration": "SETTLEMENT"})
    ]


@pytest.mark.parametrize(
    ("content", "expected", "row", "field"),
    [
        (b"\n", "header is missing", 1, "header"),
        (b"bank_ref,utr,bank_ref,value_date,narration\nb1,U1,100,2026-08-26,SETTLEMENT\n", "duplicate header", 1, "header"),
        (b"bank_ref,,credit_amount_paise,value_date,narration\nb1,U1,100,2026-08-26,SETTLEMENT\n", "blank header", 1, "header"),
        (b"bank_ref,utr,credit_amount_paise,value_date,narration,unknown\nb1,U1,100,2026-08-26,SETTLEMENT,x\n", "unexpected header", 1, "header"),
        (b"bank_ref,utr,credit_amount_paise,value_date\nb1,U1,100,2026-08-26\n", "required columns missing", 1, "header"),
        (b"bank_ref,utr,credit_amount_paise,value_date,narration\nb1,U1,100,2026-08-26,SETTLEMENT,overflow\n", "more cells", 2, "record"),
        (b"bank_ref,utr,credit_amount_paise,value_date,narration\n", "no data rows", 1, "dataset"),
        (b"bank_ref,utr,credit_amount_paise,value_date,narration\n\"unterminated", "syntax is invalid", 2, "record"),
        (b"\xff", "UTF-8 encoded", 1, "encoding"),
    ],
)
def test_invalid_csv_shape_is_quarantined(
    ingestion: IngestionService, content: bytes, expected: str, row: int, field: str
) -> None:
    """A malformed CSV shape must never be interpreted as canonical financial data."""
    result = ingestion.ingest_csv("demo_merchant", "bank_statement", "bank.csv", content)

    assert result.state == "QUARANTINED"
    assert f"source bank_statement row {row} field {field}" in (result.error or "")
    assert expected in (result.error or "")
    assert "SETTLEMENT" not in (result.error or "")


@pytest.mark.parametrize(
    ("source_type", "content", "field"),
    [
        ("merchant_orders", b"order_id,amount_paise,amount_paid_paise,status,partial_payment\no1,100,100,paid,maybe\n", "partial_payment"),
        ("bank_statement", bank_csv("b1,U1,-1,2026-08-26,SENSITIVE_ROW_CONTENT"), "credit_amount_paise"),
        ("bank_statement", bank_csv("b1,U1,1.5,2026-08-26,SENSITIVE_ROW_CONTENT"), "credit_amount_paise"),
        ("bank_statement", bank_csv("b1,U1,1.0,2026-08-26,SENSITIVE_ROW_CONTENT"), "credit_amount_paise"),
        ("merchant_orders", b"order_id,amount_paise,amount_paid_paise,currency,status,partial_payment\no1,100,100,USD,paid,false\n", "currency"),
        ("settlements", b"id,amount,status,utr,created_at\ns1,100,unknown,U1,2026-08-26\n", "status"),
        ("merchant_orders", b"order_id,amount_paise,amount_paid_paise,status,partial_payment\no1,100,100,unknown,false\n", "status"),
        ("razorpay_recon", b"entity_id,type,debit,credit,amount,settlement_id,settlement_utr\ne1,transfer,0,100,100,s1,U1\n", "type"),
        ("razorpay_recon", b"entity_id,type,debit,credit,amount,settlement_id,settlement_utr\ne1,payment,100,100,100,s1,U1\n", "debit"),
        ("razorpay_recon", b"entity_id,type,debit,credit,amount,settlement_id,settlement_utr\ne1,payment,0,0,100,s1,U1\n", "credit"),
        ("bank_statement", bank_csv(",U1,100,2026-08-26,SENSITIVE_ROW_CONTENT"), "external_id"),
        ("bank_statement", bank_csv("b1,U1,100,not-a-time,SENSITIVE_ROW_CONTENT"), "value_date"),
        ("bank_statement", bank_csv("b1,U1,100,,SENSITIVE_ROW_CONTENT"), "value_date"),
        ("settlements", b"id,amount,status,utr,created_at\ns1,100,processed,U1,\n", "created_at"),
    ],
)
def test_invalid_financial_values_are_quarantined_without_echoing_row_contents(
    ingestion: IngestionService, source_type: str, content: bytes, field: str
) -> None:
    """Permissive coercion or row-content echo would create incorrect or unsafe evidence."""
    result = ingestion.ingest_csv("demo_merchant", source_type, "source.csv", content)

    assert result.state == "QUARANTINED"
    assert f"source {source_type}" in (result.error or "")
    assert "row 2" in (result.error or "")
    assert f"field {field}" in (result.error or "")
    assert "SENSITIVE_ROW_CONTENT" not in (result.error or "")


def test_duplicate_external_id_is_quarantined_with_its_second_row(ingestion: IngestionService) -> None:
    """A duplicate transaction identifier in one delivery is ambiguous evidence, even if identical."""
    content = (
        b"bank_ref,utr,credit_amount_paise,value_date,narration\n"
        b"b1,U1,100,2026-08-26,first\n"
        b"b1,U1,100,2026-08-26,second\n"
    )

    result = ingestion.ingest_csv("demo_merchant", "bank_statement", "bank.csv", content)

    assert result.state == "QUARANTINED"
    assert "row 3 field external_id" in (result.error or "")


def test_naive_datetime_is_quarantined_as_ambiguous_source_time(ingestion: IngestionService) -> None:
    """Assigning UTC to a local wall-clock time would manufacture financial chronology."""
    result = ingestion.ingest_csv(
        "demo_merchant",
        "bank_statement",
        "bank.csv",
        bank_csv("b1,U1,100,2026-08-26T09:00:00,SENSITIVE_ROW_CONTENT"),
    )

    assert result.state == "QUARANTINED"
    assert "source bank_statement row 2 field value_date" in (result.error or "")
    assert "SENSITIVE_ROW_CONTENT" not in (result.error or "")


def test_offset_datetime_normalizes_to_canonical_utc_and_domain_rejects_naive_time() -> None:
    """Offset-bearing source times retain their instant while typed records refuse ambiguous datetimes."""
    _external_id, payload, _origins = normalize_row(
        "bank_statement",
        {
            "bank_ref": "b1",
            "utr": "U1",
            "credit_amount_paise": "100",
            "value_date": "2026-08-26T10:00:00+05:30",
            "narration": "SETTLEMENT",
        },
    )

    assert payload["value_date"] == "2026-08-26T04:30:00+00:00"
    with pytest.raises(SchemaMappingError, match="invalid timestamp"):
        normalize_row(
            "bank_statement",
            {
                "bank_ref": "b1",
                "utr": "U1",
                "credit_amount_paise": "100",
                "value_date": "2026-08-26T10:00:00",
                "narration": "SETTLEMENT",
            },
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        BankLine(
            tenant_id="demo",
            source_id="src_1",
            raw_record_id="raw_1",
            bank_ref="b1",
            credit_amount_paise=100,
            value_date="2026-08-26T10:00:00",
        )
