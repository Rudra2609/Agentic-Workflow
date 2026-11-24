"""Covering tests ran and passed (newest round of each test loop)."""

from hmap.agents.review.model import Check, Item


def check(item: Item) -> Check | None:
    tests = [t for t in item.evidence.tests if item.id in t.covers or not t.covers]
    if not tests:
        return None
    bad = [t for t in tests if t.status != "passed"]
    if not bad:
        return Check(verdict="PASS", reasons=[f"{t.name} passed" for t in tests])
    why = "; ".join(f"{t.name} {t.status}" + (f" ({t.module})" if t.module else "") +
                    (f": {t.detail[:160]}" if t.detail else "") for t in bad)
    module = next((t.module for t in bad if t.module), None)
    return Check(verdict="PARTIAL" if len(bad) < len(tests) else "FAIL", category="INCORRECT", reasons=[why],
                 module=module)
