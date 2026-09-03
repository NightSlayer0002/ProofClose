from datetime import date, datetime, time, timezone
import re

from app.domain.enums import MoneyUnit
from app.domain.money import MoneyError, parse_paise


NORMALIZATION_VERSION = "1.0"


class SchemaMappingError(ValueError):
    pass


class FieldValidationError(SchemaMappingError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


ALLOWED_COLUMNS: dict[str, set[str]] = {
    "bank_statement": {"bank_ref", "utr", "credit_amount_paise", "value_date", "narration"},
    "settlements": {"id", "amount", "status", "fees", "tax", "utr", "created_at"},
    "merchant_orders": {
        "order_id", "amount_paise", "amount_paid_paise", "amount_due_paise", "currency",
        "status", "partial_payment", "attempts", "created_at",
    },
    "razorpay_recon": {
        "entity_id", "type", "debit", "credit", "amount", "currency", "fee", "tax",
        "on_hold", "settled", "created_at", "settled_at", "settlement_id", "payment_id",
        "settlement_utr", "order_id", "order_receipt",
    },
}

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "bank_statement": {"bank_ref", "utr", "credit_amount_paise", "value_date", "narration"},
    "razorpay_recon": {"entity_id", "type", "debit", "credit", "amount", "settlement_id", "settlement_utr"},
    "settlements": {"id", "amount", "status", "utr", "created_at"},
    "merchant_orders": {"order_id", "amount_paise", "amount_paid_paise", "status", "partial_payment"},
}

SETTLEMENT_STATUSES = {"created", "pending", "processed", "failed", "cancelled", "reversed"}
ORDER_STATUSES = {"created", "attempted", "paid", "partially_paid", "cancelled"}
RECON_TYPES = {"payment", "refund"}
_WHOLE_PAISE = re.compile(r"^[0-9]+$")


def validate_headers(source_type: str, headers: list[str]) -> None:
    if source_type not in REQUIRED_COLUMNS:
        raise SchemaMappingError("unsupported source type")
    unexpected = sorted(set(headers) - ALLOWED_COLUMNS[source_type])
    if unexpected:
        raise SchemaMappingError(f"unexpected header: {unexpected[0]}")
    missing = sorted(REQUIRED_COLUMNS[source_type] - set(headers))
    if missing:
        raise SchemaMappingError(f"required columns missing: {', '.join(missing)}")


def parse_bool_strict(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise SchemaMappingError("invalid boolean")


def parse_time(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        if normalized.isdigit():
            parsed = datetime.fromtimestamp(int(normalized), tz=timezone.utc)
        elif "T" not in normalized.upper() and " " not in normalized:
            parsed = datetime.combine(date.fromisoformat(normalized), time.min, tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except (OverflowError, OSError, ValueError) as exc:
        raise SchemaMappingError("invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SchemaMappingError("invalid timestamp: timezone offset required")
    parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat()


def _money(value: str, field: str) -> int:
    normalized = value.strip()
    if not _WHOLE_PAISE.fullmatch(normalized):
        raise FieldValidationError(field, "must be a non-negative whole paise integer")
    try:
        return parse_paise(normalized, MoneyUnit.PAISE)
    except MoneyError as exc:
        raise FieldValidationError(field, "must be a non-negative whole paise integer") from exc


def _time(value: str, field: str, required: bool = False) -> str | None:
    try:
        parsed = parse_time(value)
    except SchemaMappingError as exc:
        raise FieldValidationError(field, "invalid timestamp") from exc
    if required and parsed is None:
        raise FieldValidationError(field, "timestamp is required")
    return parsed


def _bool(value: str, field: str) -> bool:
    try:
        return parse_bool_strict(value)
    except SchemaMappingError as exc:
        raise FieldValidationError(field, "invalid boolean") from exc


def _currency(row: dict[str, str]) -> str:
    if "currency" not in row:
        return "INR"
    if row["currency"] != "INR":
        raise FieldValidationError("currency", "currency must be INR")
    return "INR"


def _status(value: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise FieldValidationError("status", "unsupported status")
    return value


def normalize_row(source_type: str, row: dict[str, str]) -> tuple[str, dict, dict[str, tuple[str, object]]]:
    if source_type == "bank_statement":
        payload = {
            "bank_ref": row["bank_ref"],
            "utr": row["utr"] or None,
            "credit_amount_paise": _money(row["credit_amount_paise"], "credit_amount_paise"),
            "value_date": _time(row["value_date"], "value_date", required=True),
            "narration": row["narration"],
        }
        external_id = row["bank_ref"]
    elif source_type == "settlements":
        payload = {
            "settlement_id": row["id"],
            "amount_paise": _money(row["amount"], "amount"),
            "status": _status(row["status"], SETTLEMENT_STATUSES),
            "utr": row["utr"] or None,
            "fees_paise": _money(row.get("fees", "0"), "fees"),
            "tax_paise": _money(row.get("tax", "0"), "tax"),
            "created_at": _time(row["created_at"], "created_at", required=True),
        }
        external_id = row["id"]
    elif source_type == "merchant_orders":
        payload = {
            "order_id": row["order_id"],
            "amount_paise": _money(row["amount_paise"], "amount_paise"),
            "amount_paid_paise": _money(row["amount_paid_paise"], "amount_paid_paise"),
            "amount_due_paise": _money(row.get("amount_due_paise", "0"), "amount_due_paise"),
            "currency": _currency(row),
            "status": _status(row["status"], ORDER_STATUSES),
            "partial_payment": _bool(row["partial_payment"], "partial_payment"),
            "attempts": _money(row.get("attempts", "1"), "attempts"),
            "created_at": _time(row.get("created_at", ""), "created_at"),
        }
        external_id = row["order_id"]
    elif source_type == "razorpay_recon":
        recon_type = row["type"]
        if recon_type not in RECON_TYPES:
            raise FieldValidationError("type", "unsupported reconciliation type")
        debit = _money(row["debit"], "debit")
        credit = _money(row["credit"], "credit")
        if debit > 0 and credit > 0:
            raise FieldValidationError("debit", "debit and credit cannot both be positive")
        if debit == 0 and credit == 0:
            raise FieldValidationError("credit", "zero-movement reconciliation rows are unsupported")
        _bool(row.get("on_hold", "false"), "on_hold")
        _bool(row.get("settled", "false"), "settled")
        _currency(row)
        payload = {
            "entity_id": row["entity_id"],
            "type": recon_type,
            "debit_paise": debit,
            "credit_paise": credit,
            "amount_paise": _money(row["amount"], "amount"),
            "fee_paise": _money(row.get("fee", "0"), "fee"),
            "tax_paise": _money(row.get("tax", "0"), "tax"),
            "settlement_id": row["settlement_id"] or None,
            "settlement_utr": row["settlement_utr"] or None,
            "order_id": row.get("order_id") or None,
            "created_at": _time(row.get("created_at", ""), "created_at"),
            "settled_at": _time(row.get("settled_at", ""), "settled_at"),
        }
        external_id = row["entity_id"]
    else:
        raise SchemaMappingError("unsupported source type")
    field_origins = {field: (_raw_field(field, source_type), value) for field, value in payload.items()}
    return external_id, payload, field_origins


def validate_normalized_row(source_type: str, external_id: str, payload: dict) -> None:
    if not external_id.strip():
        raise FieldValidationError("external_id", "external ID must be non-empty")
    if source_type == "razorpay_recon":
        debit = payload["debit_paise"]
        credit = payload["credit_paise"]
        if debit > 0 and credit > 0:
            raise FieldValidationError("debit", "debit and credit cannot both be positive")
        if debit == 0 and credit == 0:
            raise FieldValidationError("credit", "zero-movement reconciliation rows are unsupported")
    if source_type == "merchant_orders" and payload["currency"] != "INR":
        raise FieldValidationError("currency", "currency must be INR")


def _raw_field(normalized_field: str, source_type: str) -> str:
    aliases = {
        "debit_paise": "debit",
        "credit_paise": "credit",
        "amount_paise": "amount" if source_type in {"razorpay_recon", "settlements"} else "amount_paise",
        "fees_paise": "fees",
        "fee_paise": "fee",
        "tax_paise": "tax",
        "settlement_id": "id" if source_type == "settlements" else "settlement_id",
    }
    return aliases.get(normalized_field, normalized_field)
