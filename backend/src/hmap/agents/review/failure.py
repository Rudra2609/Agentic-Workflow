"""Failure analyzer (Sprint 10 item 10.5, plan D5): classify each blocking item, then find the task that must fix it.

Attribution = the item's covering tasks (coverage matrix), filtered by the capability that can fix this class of
failure, refined by the evidence: a failing test's file -> the coding task that wrote that file; a missing
deliverable -> the task that should produce it. No covering task -> ``None``: a planning gap, the fix is a replan
(research §5). Low confidence (several candidates and nothing to choose by) is reported so the planner can escalate
instead of guessing.
"""

from hmap.agents.review.evidence import Bundle, _origin
from hmap.agents.review.model import Category, Decided, FailureRec

FIXER: dict[str, tuple[str, ...]] = {
    "INCORRECT": ("code.",), "UNTESTED": ("test.run",), "UNSUPPORTED_CLAIM": ("research.",),
    "DOC_MISMATCH": ("docs.",), "MISSING": ("docs.", "code.", "test.run"), "QUALITY": ("code.", "docs."),
}


def classify(d: Decided) -> tuple[Category, str]:
    if d.check.category is not None:
        return d.check.category, "; ".join(d.check.reasons)[:400]
    if d.source in ("judge", "both"):
        why = d.rationale or "the judge found it not fully met"
        ev = d.item.evidence
        if not (ev.tests or ev.verification or ev.deliverables or ev.doc_status):
            # nothing objective shows it: a requirement that was never implemented or never tested
            return ("MISSING" if d.verdict == "FAIL" else "UNTESTED"), why[:400]
        return "QUALITY", why[:400]
    return "UNTESTED", "no test, verification or deliverable shows it"


def attribute(d: Decided, category: Category, b: Bundle) -> tuple[str | None, str | None, float]:
    tasks = b.tasks
    covering = [c for c in d.item.covering if c in tasks] or list(d.item.covering)
    if not covering:
        return None, None, 1.0
    known = [c for c in covering if c in tasks]
    if not known:                           # plan ids only, no task table
        return covering[0], None, 0.6
    origins = list(dict.fromkeys(_origin(tasks[c], tasks) for c in known))
    if category == "UNTESTED":
        tests = [o for o in origins if tasks[o].capability == "test.run"]
        if not tests:                       # the test step that tests one of the covering coding tasks
            code = {o for o in origins if tasks[o].capability.startswith("code.")}
            tests = [t.task_id for t in tasks.values() if t.capability == "test.run" and t.plan_task_id
                     and not t.replaced and set(t.depends_on) & code]
        if tests:
            return tests[0], "test.run", 1.0 if len(tests) == 1 else 0.7
    prefixes = FIXER.get(category, ("code.",))
    cands = [o for o in origins if tasks[o].capability.startswith(prefixes)]
    if category == "MISSING":
        for p in prefixes:                  # the producer of that kind of deliverable, in this order
            hit = [o for o in cands if tasks[o].capability.startswith(p)]
            if hit:
                return hit[0], tasks[hit[0]].capability, 1.0 if len(hit) == 1 else 0.7
    if category == "INCORRECT" and d.check.module:
        owner = b.changed_by.get(d.check.module) or next(
            (o for f, o in b.changed_by.items() if f.endswith("/" + d.check.module) or d.check.module.endswith(f)),
            None)
        if owner and owner in tasks:
            return owner, tasks[owner].capability, 1.0
    if not cands:
        # no covering step can fix this kind of failure (the plan covered a report requirement with code steps): the
        # project's own step of that kind does (the docs step for a doc mismatch, research for an unsupported claim)
        own = [t.task_id for t in tasks.values() if t.plan_task_id and not t.replaced
               and t.capability.startswith(prefixes) and t.capability != "review.final"]
        if own:
            return own[-1], tasks[own[-1]].capability, 1.0 if len(own) == 1 else 0.7
        cands = origins
    conf = 1.0 if len(cands) == 1 else 0.6
    return cands[0], tasks[cands[0]].capability, conf


def analyse(blocking: list[Decided], b: Bundle) -> list[FailureRec]:
    out = []
    for d in blocking:
        category, why = classify(d)
        task_id, cap, conf = attribute(d, category, b)
        out.append(FailureRec(item_id=d.item.id, category=category, task_id=task_id, capability=cap, why=why,
                              confidence=conf))
    return out
