"""Deterministic checks (Sprint 10 item 10.2, plan D2): objective evidence decides first; the judge only sees what
these leave UNDECIDED.

``run(item)`` applies, in order: stub output (``stub``), deliverables (``deliverables``), covering tests (``tests``),
research verification (``verification``), documentation (``docs``), constraints (``constraints``). The first check
that decides wins; a check that finds nothing returns ``None``. Ported from the prototype's ``rules`` judge
(``samples/review/calibration/check_calibration.py``), with one change: no objective evidence at all is UNDECIDED
(the judge reads the content) instead of PARTIAL.
"""

from hmap.agents.review.checks import constraints, deliverables, docs, stub, tests, verification
from hmap.agents.review.model import Check, Item

ORDER = (stub.check, deliverables.check, tests.check, verification.check, docs.check, constraints.check)


def run(item: Item) -> Check:
    found: list[Check] = []
    for fn in ORDER:
        c = fn(item)
        if c is None:
            continue
        if c.verdict in ("FAIL", "PARTIAL") or c.no_action:
            return c
        found.append(c)
    if found:          # every check that spoke said PASS
        return Check(verdict="PASS", reasons=[r for c in found for r in c.reasons])
    return Check(verdict="UNDECIDED", reasons=["no test, verification, deliverable or document shows it"])


__all__ = ["run"]
