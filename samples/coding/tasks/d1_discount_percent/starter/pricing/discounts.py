"""Discount codes applied at checkout."""

CODES = {"SAVE10": ("percent", 10), "SAVE25": ("percent", 25), "FLAT5": ("amount", 5)}


def apply_discount(total: float, code: str | None) -> float:
    """Total after the discount code (unknown or empty codes change nothing)."""
    kind, value = CODES.get((code or "").upper(), (None, 0))
    if kind == "percent":
        return round(total - value, 2)
    if kind == "amount":
        return round(max(0.0, total - value), 2)
    return total
