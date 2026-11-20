"""DEPRECATED: the old discount table (kept for the 2023 reports, not used at checkout)."""

OLD_CODES = {"SAVE10": 10, "WINTER": 15}


def legacy_discount_percent(code: str) -> int:
    """Percent of an old discount code (0 if unknown)."""
    return OLD_CODES.get(code, 0)
