"""Checkout: discount first, then tax."""

from pricing.discounts import apply_discount
from pricing.tax import add_tax


def checkout(total: float, code: str | None = None, region: str = "default") -> float:
    return add_tax(apply_discount(total, code), region)
