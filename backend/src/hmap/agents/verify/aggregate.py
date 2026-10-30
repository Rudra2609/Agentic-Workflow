"""Aggregator: layer results → verdict + confidence + explanation (Sprint 6 item 6.6).

The decision table is data (:data:`TABLE`), checked cheapest and most reliable layer first; the first row whose
condition holds decides. Tests cover every row. Confidence is a fixed number per row — measured on the seeded
benchmark (``docs/members/6/eval.md``: the share of benchmark items reaching that row whose verdict was right),
never a number the model reports about itself. A judgement made by the fallback rules (no model) is capped at
:data:`RULES_CAP`.

| row | condition (first match wins)                        | verdict             |
|-----|-----------------------------------------------------|---------------------|
| R1  | L1 fails (a quote / hash / URL does not check out)  | UNSUPPORTED         |
| R2  | L1 passes, L2 off (ablation "L1 only")              | VERIFIED            |
| R3  | L2: the quotes contradict the claim                 | UNSUPPORTED         |
| R4  | L2 unsure (the two orders disagree)                 | NEEDS_MORE_RESEARCH |
| R5  | L2: the quotes do not state the claim               | UNSUPPORTED         |
| R6  | L2 supports, L4 finds a conflicting source          | CONFLICTING         |
| R7  | L2 supports, another site agrees, no conflict       | VERIFIED            |
| R8  | L2 supports, nothing else found (or L3/L4 off)      | VERIFIED            |

A claim split into parts gets its worst part's verdict (UNSUPPORTED > CONFLICTING > NEEDS_MORE_RESEARCH > VERIFIED).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from hmap.agents.verify import compare, mechanical
from hmap.agents.verify.model import AtomCheck, ClaimCheck
from hmap.core.contracts.domain import Verdict


@dataclass(frozen=True)
class Row:
    id: str
    verdict: Verdict
    when: Callable[[AtomCheck, frozenset[str]], bool]
    why: str


def _l2(a: AtomCheck) -> str:
    return a.l2.label if a.l2 is not None else ""


TABLE: tuple[Row, ...] = (
    Row("R1", "UNSUPPORTED", lambda a, L: not mechanical.passed(a.l1),
        "a cited quote does not check out against the saved page"),
    Row("R2", "VERIFIED", lambda a, L: "l2" not in L, "every cited quote is verbatim in its saved page (L1 only)"),
    Row("R3", "UNSUPPORTED", lambda a, L: _l2(a) == "refutes", "the cited quotes contradict the claim"),
    Row("R4", "NEEDS_MORE_RESEARCH", lambda a, L: a.l2 is not None and a.l2.unsure,
        "the check is unsure: the judge answered differently when the order was swapped"),
    Row("R5", "UNSUPPORTED", lambda a, L: _l2(a) != "supports", "the cited quotes do not state the claim"),
    Row("R6", "CONFLICTING", lambda a, L: any(c.conflict for c in a.l4), "another source says otherwise"),
    Row("R7", "VERIFIED", lambda a, L: bool(a.independent_hosts),
        "the quotes support the claim and an independent source agrees"),
    Row("R8", "VERIFIED", lambda a, L: True, "the quotes support the claim"),
)

# Per-row accuracy on samples/verify/benchmark.jsonl (replay, 2026-10-18; eval.md §3), rounded down and capped at
# 0.98; rows with fewer than 10 items or none are set by judgement (R4: unsure by definition; R7 never reached).
# Re-measure when a prompt or the table changes.
CONFIDENCE: dict[str, float] = {"R1": 0.98, "R2": 0.3, "R3": 0.95, "R4": 0.5, "R5": 0.85, "R6": 0.9, "R7": 0.9,
                                "R8": 0.8}
RULES_CAP = 0.6
SEVERITY: dict[str, int] = {"VERIFIED": 0, "NEEDS_MORE_RESEARCH": 1, "CONFLICTING": 2, "UNSUPPORTED": 3}


def decide(atom: AtomCheck, layers: frozenset[str]) -> AtomCheck:
    row = next(r for r in TABLE if r.when(atom, layers))
    conf = CONFIDENCE[row.id]
    if atom.l2 is not None and atom.l2.by == "rules" and row.id != "R1":
        conf = min(conf, RULES_CAP)
    atom.row, atom.verdict, atom.confidence = row.id, row.verdict, conf
    atom.explanation = explain(atom, row)
    return atom


def explain(atom: AtomCheck, row: Row) -> str:
    parts = [row.why]
    if row.id == "R1":
        parts += [f"{r.evidence_id}: {r.detail}" for r in atom.l1 if not r.ok]
    elif atom.l2 is not None and row.id in ("R3", "R4", "R5", "R6", "R7", "R8"):
        if atom.l2.rationale:
            parts.append(f"judge: {atom.l2.rationale}")
        if atom.l2.guard:
            parts.append(atom.l2.guard)
    if row.id == "R6":
        for c in atom.l4:
            if c.conflict:
                why = c.judgement.rationale if c.judgement else ""
                parts.append(f"{c.passage.host}: \"{c.passage.text[:160]}\"" + (f" ({why})" if why else ""))
        if newer := compare.newer_source(atom.l4):
            parts.append(newer)
    if row.id == "R7":
        parts.append("agreeing sites: " + ", ".join(atom.independent_hosts))
    return " — ".join(p for p in parts if p)


def roll_up(claim: ClaimCheck) -> ClaimCheck:
    worthy = [a for a in claim.atoms if a.check_worthy] or claim.atoms
    worst = max(worthy, key=lambda a: (SEVERITY[a.verdict], -a.confidence))
    claim.verdict = worst.verdict
    claim.confidence = (min(a.confidence for a in worthy) if worst.verdict == "VERIFIED" else worst.confidence)
    if len(worthy) == 1:
        claim.explanation = worst.explanation
    else:
        claim.explanation = "; ".join(f"[{a.atom_id}] {a.verdict.lower().replace('_', ' ')}: {a.explanation}"
                                      for a in worthy)
    claim.supporting = list(claim.evidence_ids) if worst.verdict in ("VERIFIED", "CONFLICTING") else []
    claim.supporting += sorted({c.passage.url for a in worthy for c in a.l4 if c.agrees})
    claim.contradicting = sorted({c.passage.url for a in worthy for c in a.l4 if c.conflict})
    if worst.verdict == "UNSUPPORTED" and worst.row in ("R1", "R3"):
        claim.contradicting = [*claim.contradicting, *[r.evidence_id for r in worst.l1 if not r.ok]]
    return claim


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if len(text) > 1 and text[1].islower() else text


def follow_up_questions(claims: Sequence[ClaimCheck], limit: int = 3) -> list[str]:
    """Gap questions for follow-up research (6.8): the flagged claims, least settled first."""
    order = {"NEEDS_MORE_RESEARCH": 0, "UNSUPPORTED": 1, "CONFLICTING": 2}
    flagged = sorted((c for c in claims if c.verdict in order), key=lambda c: (order[c.verdict], c.claim_id))
    out: list[str] = []
    for c in flagged:
        text = c.text.strip().rstrip(".")
        q = (f"Which sources are right about: {text}?" if c.verdict == "CONFLICTING"
             else f"Is it true that {_lower_first(text)}?")
        if q not in out:
            out.append(q[:300])
        if len(out) >= limit:
            break
    return out
