"""Aggregation and scoring (Sprint 10 item 10.4, plan D4): objective signals first.

``combine(objective, judge)`` is the precedence table (tested row by row):

| objective   | judge          | verdict | source    |
|-------------|----------------|---------|-----------|
| FAIL        | any            | FAIL    | objective |
| PARTIAL     | any            | PARTIAL | objective |
| PASS        | none / PASS    | PASS    | objective / both |
| PASS        | PARTIAL / FAIL | PARTIAL | both (the judge saw a quality gap the checks cannot) |
| UNDECIDED   | PASS/PARTIAL/FAIL | the judge's | judge |
| UNDECIDED   | none           | PARTIAL | none ("not judged") |

The recommendation: every must item PASS (stub-only gaps excepted) -> PASS; a failure a revision can fix -> REVISE;
otherwise -> ESCALATE.
"""

from hmap.agents.review.model import CheckVerdict, Decided, Verdict


def combine(objective: CheckVerdict, judge: Verdict | None) -> tuple[Verdict, str]:
    if objective in ("FAIL", "PARTIAL"):
        return objective, "objective"
    if objective == "PASS":
        if judge in (None, "PASS"):
            return "PASS", "objective" if judge is None else "both"
        return "PARTIAL", "both"
    if judge is None:
        return "PARTIAL", "none"
    return judge, "judge"


def score_criterion(d: Decided, completeness: float) -> float:
    """Marks for a rubric criterion: the judge's level when it picked one, else the completeness share."""
    mx = d.item.max_marks or 0.0
    if d.level is not None:
        for lv in d.item.rubric_levels:
            if str(lv.get("label")) == d.level and lv.get("marks") is not None:
                return min(mx, float(lv["marks"]))
    return round(mx * completeness, 2)


def completeness(decided: list[Decided]) -> float:
    must = [d for d in decided if d.item.kind != "criterion" and d.item.priority == "must"]
    if not must:
        must = [d for d in decided if d.item.kind != "criterion"]
    if not must:
        return 0.0
    got = sum(1.0 if d.verdict == "PASS" else 0.5 if d.verdict == "PARTIAL" else 0.0 for d in must)
    return round(got / len(must), 3)


def blocking(decided: list[Decided]) -> list[Decided]:
    """Items that stop a PASS: must requirements / constraints / deliverables / change requests not PASS, and any
    FAIL. A must requirement nothing shows (not judged, no evidence) blocks too: it is untested. Stub output does not
    block (no revision can fix a placeholder), nor does a constraint / deliverable nothing could check."""
    out = []
    for d in decided:
        if d.item.kind == "criterion" or d.verdict == "PASS":
            continue
        if d.check.no_action:
            continue
        if d.source == "none" and d.item.kind != "requirement":
            continue     # a constraint / deliverable nothing could check (a process rule, a format): noted, not blocked
        if d.verdict == "FAIL" or d.item.priority == "must":
            out.append(d)
    return out
