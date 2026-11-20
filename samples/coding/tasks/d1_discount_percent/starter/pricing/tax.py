"""Sales tax per region."""

RATES = {"default": 0.08, "food": 0.0}


def add_tax(total: float, region: str = "default") -> float:
    return round(total * (1 + RATES.get(region, RATES["default"])), 2)
