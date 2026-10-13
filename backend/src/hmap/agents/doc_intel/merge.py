"""Merge, dedup and ids (spec item 2.6). Candidates come from the LLM (per chunk), from tables (criteria and
deliverables) and from the rule pass (only when no model answered). Ids R1.. C1.. D1.. E1.. follow document order,
so the same document always gets the same ids."""

from dataclasses import dataclass, field

from hmap.agents.doc_intel.extract.quotes import jaccard, normalize
from hmap.agents.doc_intel.model import Block, SourceDocument
from hmap.core.contracts.domain import (
    Constraint,
    Deliverable,
    EvaluationCriterion,
    Requirement,
    RubricLevel,
    SourceRef,
)

# confidence by where an item came from (doc 01: confidence 0..1)
CONF_TABLE = 0.95
CONF_EXACT = 0.9
CONF_RULE_AGREES = 0.05
CONF_APPROXIMATE = 0.7
CONF_UNVERIFIED = 0.4
CONF_RULES_ONLY = 0.6
DUPLICATE_JACCARD = 0.8


@dataclass
class Candidate:
    kind: str                                   # R | C | D | E
    text: str
    doc_index: int
    document: SourceDocument
    block: Block | None = None
    quote: str | None = None
    char_span: tuple[int, int] | None = None
    confidence: float = CONF_EXACT
    origin: str = "llm"                         # llm | table | rules
    priority: str = "must"
    rtype: str = "functional"
    ckind: str = "other"
    name: str = ""
    fmt: str = ""
    max_marks: float = 0.0
    levels: list[tuple[str, str, float | None]] = field(default_factory=list)

    @property
    def order(self) -> tuple[int, int, int]:
        start = self.char_span[0] if self.char_span else (self.block.char_start if self.block else 10**9)
        return (self.doc_index, start, 0 if self.origin == "table" else 1)

    def source_ref(self) -> SourceRef:
        return SourceRef(doc_id=self.document.doc_id, page=self.block.page if self.block else None,
                         block_ids=[self.block.id] if self.block else [], char_span=self.char_span,
                         quote=self.quote, folder=self.document.folder)


def _same(a: Candidate, b: Candidate) -> bool:
    if a.doc_index != b.doc_index:
        return False
    if a.quote and b.quote and normalize(a.quote) == normalize(b.quote):
        return True
    return jaccard(a.text, b.text) >= DUPLICATE_JACCARD


def dedup(candidates: list[Candidate]) -> list[Candidate]:
    """Same item twice (e.g. chunk overlap or a re-ask) -> keep the more confident one. The same quote under two
    kinds -> keep the first (document order) so an item is never both a requirement and a constraint."""
    kept: list[Candidate] = []
    for cand in sorted(candidates, key=lambda c: (c.order, -c.confidence)):
        twin = next((k for k in kept if (k.kind == cand.kind or (k.quote and cand.quote and k.kind != "E"
                                                                  and cand.kind != "E")) and _same(k, cand)), None)
        if twin is None:
            kept.append(cand)
        elif cand.confidence > twin.confidence and twin.kind == cand.kind:
            kept[kept.index(twin)] = cand
    return kept


@dataclass
class Assembled:
    requirements: list[Requirement] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    deliverables: list[Deliverable] = field(default_factory=list)
    evaluation_criteria: list[EvaluationCriterion] = field(default_factory=list)


def assemble(candidates: list[Candidate]) -> Assembled:
    out = Assembled()
    for cand in sorted(dedup(candidates), key=lambda c: c.order):
        conf = round(min(1.0, max(0.0, cand.confidence)), 2)
        if cand.kind == "R":
            out.requirements.append(Requirement(
                id=f"R{len(out.requirements) + 1}", text=cand.text, type=cand.rtype,
                priority=cand.priority, source_ref=cand.source_ref(), confidence=conf))
        elif cand.kind == "C":
            out.constraints.append(Constraint(id=f"C{len(out.constraints) + 1}", text=cand.text,
                                              kind=cand.ckind, source_ref=cand.source_ref()))
        elif cand.kind == "D":
            out.deliverables.append(Deliverable(id=f"D{len(out.deliverables) + 1}", name=cand.name or cand.text,
                                                format=cand.fmt, source_ref=cand.source_ref()))
        elif cand.kind == "E":
            out.evaluation_criteria.append(EvaluationCriterion(
                id=f"E{len(out.evaluation_criteria) + 1}", criterion=cand.text, max_marks=cand.max_marks,
                rubric_levels=[RubricLevel(label=lab, description=desc, marks=m) for lab, desc, m in cand.levels],
                source_ref=cand.source_ref()))
    return out
