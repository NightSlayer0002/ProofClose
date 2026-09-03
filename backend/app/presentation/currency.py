"""Deterministic Indian currency formatting for integer paise."""


def format_inr_paise(value: int) -> str:
    """Format an integer amount in paise using Indian digit grouping.

    Money is authoritative as integer paise throughout the application.  This
    helper deliberately rejects bools and coercible values so presentation
    cannot hide an upstream type error.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("value must be an integer number of paise")
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    rupees, paise = divmod(absolute, 100)
    rupee_text = str(rupees)
    if len(rupee_text) > 3:
        suffix = rupee_text[-3:]
        prefix = rupee_text[:-3]
        groups: list[str] = []
        while prefix:
            groups.append(prefix[-2:])
            prefix = prefix[:-2]
        rupee_text = ",".join([*reversed(groups), suffix])
    return f"{sign}₹{rupee_text}.{paise:02d}"
