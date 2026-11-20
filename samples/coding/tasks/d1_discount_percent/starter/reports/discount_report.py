"""Monthly report: how often each discount code was used and the percent saved per order total."""


def usage(orders: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for o in orders:
        code = o.get("discount_code")
        if code:
            out[code] = out.get(code, 0) + 1
    return out
