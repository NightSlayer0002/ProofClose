from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.enums import MoneyUnit


class MoneyError(ValueError):
    pass


def parse_paise(value: Any, unit: MoneyUnit) -> int:
    if isinstance(value, bool):
        raise MoneyError("booleans are not money")
    if isinstance(value, float):
        raise MoneyError("floats are not allowed for authoritative money")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"invalid money value: {value!r}") from exc
    paise = amount if unit is MoneyUnit.PAISE else amount * 100
    if not paise.is_finite() or paise != paise.to_integral_value():
        raise MoneyError("money must resolve to whole paise")
    return int(paise)


def format_inr(paise: int) -> str:
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise MoneyError("formatted money must be integer paise")
    negative = paise < 0
    absolute = abs(paise)
    rupees, subunits = divmod(absolute, 100)
    digits = str(rupees)
    if len(digits) > 3:
        tail = digits[-3:]
        head = digits[:-3]
        groups: list[str] = []
        while head:
            groups.append(head[-2:])
            head = head[:-2]
        grouped = ",".join(reversed(groups)) + "," + tail
    else:
        grouped = digits
    sign = "-" if negative else ""
    return f"{sign}₹{grouped}.{subunits:02d}"
