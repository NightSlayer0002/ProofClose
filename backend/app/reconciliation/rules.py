from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import Decision, ExceptionType
from app.domain.models import ConfigurationBundle


SETTLEMENT_RULE_NAME = "settlement_match"
SETTLEMENT_RULE_VERSION_V1 = "1.0"
SETTLEMENT_RULE_VERSION_V2 = "2.0"
ORDER_RULE_NAME = "order_payment_consistency"
ORDER_RULE_VERSION_V1 = "1.0"
CONFIGURATION_VERSION = "2.0"

# Compatibility aliases for current settlement execution.
RULE_NAME = SETTLEMENT_RULE_NAME
RULE_VERSION = SETTLEMENT_RULE_VERSION_V2


@dataclass(frozen=True)
class ReconciliationPolicy:
    pending_hours: int = 3
    amount_candidate_window_hours: int = 48


@dataclass(frozen=True)
class ReconciliationPolicyV2:
    pending_hours: int = 3
    bank_match_window_hours: int = 48
    early_bank_tolerance_hours: int = 2
    future_clock_skew_minutes: int = 5


@dataclass(frozen=True)
class EvaluationContext:
    configuration: ConfigurationBundle
    evaluated_at: datetime


@dataclass(frozen=True)
class OrderDecision:
    status: Decision
    exception_type: ExceptionType
    payment_row_count: int
    settled_payment_paise: int
    excess_payment_paise: int
    reasons: tuple[str, ...]
    score: int = 100
