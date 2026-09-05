"""Public input documentation derived from the same schema used by ingestion."""
from app.normalization.adapters import ALLOWED_COLUMNS, REQUIRED_COLUMNS, NORMALIZATION_VERSION

SOURCE_LABELS = {
    "merchant_orders": "Merchant orders",
    "razorpay_recon": "Payment and refund ledger",
    "settlements": "Provider settlements",
    "bank_statement": "Bank credits",
}
MONEY_COLUMNS = {
    "merchant_orders": {"amount_paise", "amount_paid_paise", "amount_due_paise"},
    "razorpay_recon": {"debit", "credit", "amount", "fee", "tax"},
    "settlements": {"amount", "fees", "tax"},
    "bank_statement": {"credit_amount_paise"},
}


def source_catalog(max_bytes: int, max_rows: int) -> dict:
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "currency": "INR",
        "money_unit": "integer paise (including amount, debit and credit)",
        "max_bytes": max_bytes,
        "max_rows": max_rows,
        "sources": [
            {
                "source_type": source_type,
                "label": label,
                "required_columns": sorted(REQUIRED_COLUMNS[source_type]),
                "optional_columns": sorted(ALLOWED_COLUMNS[source_type] - REQUIRED_COLUMNS[source_type]),
                "money_columns": sorted(MONEY_COLUMNS[source_type]),
                "template_csv": ",".join(sorted(ALLOWED_COLUMNS[source_type])) + "\n",
            }
            for source_type, label in SOURCE_LABELS.items()
        ],
    }
