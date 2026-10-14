"""Refinement of Member 2's ``document.extract`` result (Sprint 4 item 4.10). Member 2's folder is not edited: this
adapter runs through the runtime hook (plan D1) and only calls Member 2's public functions (quote location, the rule
pass, the set's validation, the confidence constants).

Critics (programmatic first, spec §3):
- ``quotes``    every item's quote must be found in the documents (``locate``); otherwise HALLUCINATION (major);
- ``contract``  the set's own checks (marks add up to the stated total, at least one requirement, no duplicates);
- ``priority``  a requirement whose own quote says *must / should / may* must carry that priority (FACTUAL);
- ``coverage``  sentences the keyword rules flag that no item covers (OMISSION, *minor*: a hint for the judge);
- ``judge``     an LLM rubric over the document text: missing items, invented / background items, wrong kind,
                wrong priority — every issue names an item id or the list a missing item belongs in.

Reviser (targeted): deterministic fixes first (a programmatic issue with a machine-readable fix, e.g. the priority),
then the model proposes ``add`` / ``drop`` / ``set`` changes. Guards: an added item must quote a sentence that is in
the documents and is not already listed; ``drop`` / ``set`` only on flagged items (``full`` / ``widen`` strategies may
touch any item). Unflagged items stay exactly as they were; the result must still validate as a ``RequirementSet``.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from hmap.agents.doc_intel.extract.quotes import QuoteMatch, jaccard, locate, overlap
from hmap.agents.doc_intel.extract.rules import MODAL_RE, RuleHit, priority_of, rule_pass
from hmap.agents.doc_intel.merge import CONF_APPROXIMATE, CONF_EXACT
from hmap.agents.doc_intel.model import Block, DocumentModel, SourceDocument
from hmap.agents.doc_intel.tables import read_table, stated_total
from hmap.agents.doc_intel.validate import check as check_set
from hmap.agents.refine.core import Attempt, Critique, Issue, RefineContext, Revision, Strategy
from hmap.agents.refine.critics import Criterion, LLMRubricCritic, ProgrammaticCritic, Rubric
from hmap.agents.refine.integration import RefineSetup
from hmap.agents.refine.revisers import reflection_lines
from hmap.agents.refine.stop import StopPolicy
from hmap.core.contracts import TaskAssign, TaskResult
from hmap.core.contracts.domain import Constraint, Deliverable, Requirement, RequirementSet, SourceRef
from hmap.core.errors import Cancelled
from hmap.core.llm.base import Message
from hmap.core.runtime.base import AgentContext
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine.extraction")

ARTIFACT_TYPE = "requirement-set"
MODEL_TYPE = "document-model"
LISTS: dict[str, tuple[str, str]] = {"requirement": ("requirements", "R"), "constraint": ("constraints", "C"),
                                     "deliverable": ("deliverables", "D")}
LIST_KIND = {v[0]: k for k, v in LISTS.items()}
WINDOW_CHARS = 12_000
FIX_RE = re.compile(r"^set (priority|req_type)=(\w+)$")


# ---------------------------------------------------------------------------------------------- input


@dataclass
class ExtractionInput:
    """What the output is checked against: the parsed documents and the rule pass over them."""

    model: DocumentModel
    hits: list[RuleHit] = field(default_factory=list)
    totals: list[float] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)   # quotes / texts a revision removed (not offered again)

    @property
    def docs(self) -> list[SourceDocument]:
        return self.model.documents

    def doc(self, doc_id: str | None) -> SourceDocument | None:
        return next((d for d in self.docs if d.doc_id == doc_id), None)


def _doc_total(doc: SourceDocument) -> float | None:
    prose = "\n".join(b.text for b in doc.blocks if b.type not in ("table", "header", "footer", "note"))
    total = stated_total(prose)
    if total is None:
        for table in doc.tables:
            total = read_table(table.rows).total
            if total is not None:
                break
    return total


def build_input(model: DocumentModel) -> ExtractionInput:
    totals = [t for t in (_doc_total(d) for d in model.documents) if t is not None]
    return ExtractionInput(model=model, hits=rule_pass(model.documents), totals=totals)


def _content_blocks(doc: SourceDocument) -> list[Block]:
    return [b for b in doc.blocks if b.type not in ("header", "footer")]


def find(inp: ExtractionInput, text: str, doc_id: str | None = None) -> tuple[SourceDocument | None, QuoteMatch]:
    """Best location of ``text`` in the item's own document (or any document)."""
    docs = [d for d in inp.docs if doc_id is None or d.doc_id == doc_id] or inp.docs
    best: tuple[SourceDocument | None, QuoteMatch] = (None, QuoteMatch(None, "unverified"))
    rank = {"exact": 2, "approximate": 1, "unverified": 0}
    for d in docs:
        m = locate(text, _content_blocks(d))
        if rank[m.status] > rank[best[1].status] or (rank[m.status] == rank[best[1].status]
                                                     and m.score > best[1].score):
            best = (d, m)
        if m.status == "exact":
            break
    return best


def verified(inp: ExtractionInput, quote: str, doc_id: str | None = None) -> QuoteMatch:
    """``locate`` the quote; a list item under a lead-in is quoted as "<lead-in>: <item>." by Member 2's rules, so
    when the whole is not one sentence of the document, its item part is located instead."""
    _, m = find(inp, quote, doc_id)
    if m.status == "unverified" and ":" in quote:
        lead, tail = quote.split(":", 1)
        _, tail_match = find(inp, tail.strip().rstrip("."), doc_id)
        if tail_match.status != "unverified" and find(inp, lead.strip(), doc_id)[1].status != "unverified":
            return tail_match
    return m


def was_dropped(inp: ExtractionInput, text: str) -> bool:
    return any(overlap(text, d) >= 0.8 or overlap(d, text) >= 0.8 for d in inp.dropped)


Item = Requirement | Constraint | Deliverable


def items(rs: RequirementSet) -> list[tuple[str, Item]]:
    return [*(("requirement", r) for r in rs.requirements), *(("constraint", c) for c in rs.constraints),
            *(("deliverable", d) for d in rs.deliverables)]


def item_text(item: Item) -> str:
    return item.name if isinstance(item, Deliverable) else item.text


# ---------------------------------------------------------------------------------------------- critics


def check_quotes(rs: RequirementSet, inp: ExtractionInput) -> list[Issue]:
    out: list[Issue] = []
    for kind, it in items(rs):
        ref = it.source_ref
        quote = ref.quote if ref else None
        doc = inp.doc(ref.doc_id) if ref else None
        name = doc.name if doc is not None else "the documents"
        if quote:
            m = verified(inp, quote, ref.doc_id if ref else None)
            if m.status == "unverified":
                out.append(Issue(category="HALLUCINATION", severity="major", location=it.id,
                                 description=f"The quote of {it.id} is not in {name}.",
                                 evidence=quote[:300], fix_hint="quote the source sentence exactly, or drop the item"))
        elif kind == "requirement":
            _, m = find(inp, item_text(it), ref.doc_id if ref else None)
            if m.status == "unverified":
                out.append(Issue(category="HALLUCINATION", severity="major", location=it.id,
                                 description=f"{it.id} has no source sentence in {name}.",
                                 fix_hint="find its sentence in the document, or drop the item"))
            else:
                out.append(Issue(category="HALLUCINATION", severity="minor", location=it.id,
                                 description=f"{it.id} has no verified quote.",
                                 fix_hint="add the exact source sentence as its quote"))
    return out


def check_contract(rs: RequirementSet, inp: ExtractionInput) -> list[Issue]:
    out: list[Issue] = []
    report = check_set(rs, inp.totals)
    if "marks_sum_mismatch" in report.issues:
        out.append(Issue(category="CONSISTENCY", severity="major", location="evaluation_criteria",
                         description="The marking criteria do not add up to the total the document states.",
                         fix_hint="check each criterion's marks against the marking table"))
    if "no_requirements" in report.issues and not rs.evaluation_criteria:   # a marking rubric may have none
        out.append(Issue(category="OMISSION", severity="major", location="requirements",
                         description="No requirements were extracted.",
                         fix_hint="extract the document's requirements, or check whether an item listed as a "
                                  "constraint or deliverable is really a requirement"))
    for kind in LISTS:
        same = [it for k, it in items(rs) if k == kind]
        for i, a in enumerate(same):
            for b in same[i + 1:]:
                if jaccard(item_text(a), item_text(b)) >= 0.85:
                    out.append(Issue(category="CONSISTENCY", severity="minor", location=b.id,
                                     description=f"{b.id} duplicates {a.id}.", fix_hint=f"drop {b.id}"))
    return out


def check_priority(rs: RequirementSet, inp: ExtractionInput) -> list[Issue]:
    """A modal verb in the requirement's own quote decides its priority (must / should / could)."""
    out: list[Issue] = []
    for r in rs.requirements:
        quote = r.source_ref.quote
        if not quote or not (m := MODAL_RE.search(quote)):
            continue
        expected = priority_of(quote)
        if expected != r.priority:
            out.append(Issue(category="FACTUAL", severity="major", location=r.id,
                             description=f"{r.id} says \"{m.group(1)}\" but has priority {r.priority}.",
                             evidence=quote[:200], fix_hint=f"set priority={expected}"))
    return out


def _covered(hit: RuleHit, rs: RequirementSet) -> bool:
    for _, it in items(rs):
        ref = it.source_ref
        if ref is not None and hit.block_id in ref.block_ids and overlap(hit.text, ref.quote or item_text(it)) >= 0.5:
            return True
        if overlap(hit.text, item_text(it)) >= 0.75 or (ref and ref.quote and overlap(hit.text, ref.quote) >= 0.75):
            return True
    return False


def check_coverage(rs: RequirementSet, inp: ExtractionInput) -> list[Issue]:
    """Sentences the keyword rules flag that no item covers: a hint (minor), the judge decides."""
    out: list[Issue] = []
    for hit in inp.hits:
        if _covered(hit, rs) or was_dropped(inp, hit.text):
            continue
        kind = {"R": "requirement", "C": "constraint", "D": "deliverable"}[hit.kind]
        out.append(Issue(category="OMISSION", severity="minor", location=LISTS[kind][0],
                         description=f"A sentence that looks like a {kind} is not listed.",
                         evidence=hit.text[:300], fix_hint=f"add it as a {kind} if the document requires it"))
    return out[:8]


EXTRACTION_RUBRIC = Rubric(
    name="extraction", version="1", subject="a list of requirements, constraints and deliverables extracted from "
    "course or project documents",
    criteria=(
        Criterion("E1", "Completeness: is every requirement, constraint and deliverable that the document states "
                  "listed? For each missing one, quote its exact sentence from the document as evidence.", 1.5,
                  "OMISSION"),
        Criterion("E2", "Faithfulness: is every listed item actually required by the document (not invented, not "
                  "background, not a reading instruction)?", 1.0, "HALLUCINATION"),
        Criterion("E3", "Kind: requirement = what the solution or the work must do or be; constraint = a limit on how "
                  "or with what (language, library, team size, deadline, page limit); deliverable = what to hand "
                  "in. Is each item the right kind?", 0.5, "FACTUAL"),
        Criterion("E4", "Priority: must (must, shall, required, a plain instruction), should (should, recommended), "
                  "could (may, optional, extra credit). Is each requirement's priority right?", 0.5, "FACTUAL"),
    ),
    instructions="Conventions (the same as the extractor's): one item per sentence or list item; setup steps that "
                 "are not marked or checked (install a tool, clone a repository, create an environment), background, "
                 "motivation and reading instructions are NOT items; a sentence ending with ':' that introduces a "
                 "list is not an item, the list items under it are. Marking tables and their criteria (E ids) are "
                 "checked by code: do not report them.",
    location_hint="the item id (R3, C1, D2); for a missing item the list it belongs in: requirements, constraints "
                  "or deliverables")


def windows(inp: ExtractionInput, limit: int = WINDOW_CHARS) -> list[list[tuple[SourceDocument, list[Block]]]]:
    """Documents (or block runs of a long one) packed into windows of at most ``limit`` characters."""
    pieces: list[tuple[SourceDocument, list[Block]]] = []
    for d in inp.docs:
        run: list[Block] = []
        size = 0
        for b in _content_blocks(d):
            if run and size + len(b.text) > limit:
                pieces.append((d, run))
                run, size = [], 0
            run.append(b)
            size += len(b.text) + 1
        pieces.append((d, run))
    out: list[list[tuple[SourceDocument, list[Block]]]] = []
    size = limit + 1
    for d, blocks in pieces:
        n = sum(len(b.text) + 1 for b in blocks)
        if size + n > limit:
            out.append([])
            size = 0
        out[-1].append((d, blocks))
        size += n
    return out


def _item_line(kind: str, it: Item) -> str:
    ref = it.source_ref
    if isinstance(it, Requirement):
        head = f"{it.id} [requirement, {it.priority}, {it.type}]"
    elif isinstance(it, Constraint):
        head = f"{it.id} [constraint, {it.kind}]"
    else:
        head = f"{it.id} [deliverable{', ' + it.format if it.format else ''}]"
    quote = f" | quote: \"{ref.quote}\"" if ref and ref.quote else ""
    return f"{head} {item_text(it)}{quote}"


def render_window(rs: RequirementSet, window: list[tuple[SourceDocument, list[Block]]], first: bool) -> str:
    docs = []
    block_ids = {b.id for _, blocks in window for b in blocks}
    doc_ids = {d.doc_id for d, _ in window}
    for d, blocks in window:
        label = f"{d.folder}/{d.name}" if d.folder else d.name
        lines = [f"- {b.text}" if b.type == "list_item" else (f"## {b.text}" if b.type == "heading" else b.text)
                 for b in blocks]
        docs.append(f"=== Document: {label}\n" + "\n".join(lines))
    shown = []
    for kind, it in items(rs):
        ref = it.source_ref
        if ref is None:
            if first:
                shown.append(_item_line(kind, it))
        elif ref.doc_id in doc_ids and (not ref.block_ids or set(ref.block_ids) & block_ids):
            shown.append(_item_line(kind, it))
    return "\n\n".join(docs) + "\n\n=== Extracted items\n" + ("\n".join(shown) or "(none)")


def _locations(rs: RequirementSet, inp: Any) -> list[str]:
    return [it.id for _, it in items(rs)] + list(LIST_KIND)


def _keep(issue: Issue, rs: RequirementSet, inp: ExtractionInput) -> bool:
    """D8 for the judge: "not in the document" about an item whose quote verifiably IS in the document is dropped."""
    if issue.category != "HALLUCINATION" or not re.search(r"not (?:in|found|stated|mentioned)|invent|does not appear",
                                                          issue.description, re.I):
        return True
    it = next((it for _, it in items(rs) if it.id == (issue.location or "").strip()), None)
    if it is None or not it.source_ref or not it.source_ref.quote:
        return True
    return find(inp, it.source_ref.quote, it.source_ref.doc_id)[1].status != "exact"


def _window_renderer(window: list[tuple[SourceDocument, list[Block]]],
                     first: bool) -> Callable[[RequirementSet, Any], str]:
    def render(output: RequirementSet, task_input: Any) -> str:
        return render_window(output, window, first)
    return render


class ExtractionJudge:
    """The LLM rubric over each document window (the gold documents fit one window; long uploads take several)."""

    kind: Literal["programmatic", "llm"] = "llm"
    name = "judge"

    def __init__(self, role: str = "judge", weight: float = 3.0) -> None:
        self.role = role
        self.weight = weight

    async def review(self, output: RequirementSet, task_input: ExtractionInput, ctx: RefineContext) -> Critique:
        parts: list[tuple[int, Critique]] = []
        for n, window in enumerate(windows(task_input)):
            critic = LLMRubricCritic(EXTRACTION_RUBRIC, role=self.role, name=self.name, locations=_locations,
                                     render=_window_renderer(window, n == 0))
            part = await critic.review(output, task_input, ctx)
            size = sum(len(b.text) for _, blocks in window for b in blocks) or 1
            parts.append((size, part))
        total = sum(s for s, _ in parts) or 1
        score = sum(s * p.score for s, p in parts) / total
        issues = [i for _, p in parts for i in p.issues if _keep(i, output, task_input)]
        return Critique(score=round(score, 4), issues=issues, critic=self.name)


def extraction_critics(inp: ExtractionInput, *, judge: bool = True) -> list[Any]:
    critics: list[Any] = [
        ProgrammaticCritic(lambda rs, i: check_quotes(rs, i), name="quotes"),
        ProgrammaticCritic(lambda rs, i: check_contract(rs, i), name="contract", covers={"SCHEMA"}),
        ProgrammaticCritic(lambda rs, i: check_priority(rs, i), name="priority"),
        ProgrammaticCritic(lambda rs, i: check_coverage(rs, i), name="coverage", weight=0.5),
    ]
    if judge:
        critics.append(ExtractionJudge())
    return critics


# ---------------------------------------------------------------------------------------------- reviser


class Change(BaseModel):
    op: Literal["add", "drop", "set"]
    kind: Literal["requirement", "constraint", "deliverable"] = "requirement"
    id: str = ""
    field: Literal["priority", "req_type", "kind", "text", ""] = ""
    value: str = ""
    text: str = ""
    quote: str = Field(default="", description="for add: the exact sentence copied from the document")
    priority: Literal["must", "should", "could"] = "must"
    req_type: Literal["functional", "non_functional"] = "functional"
    constraint_kind: Literal["technology", "format", "process", "resource", "other"] = "other"
    deliverable_name: str = ""
    deliverable_format: str = ""
    issue: int | None = None

    @field_validator("id", "value", "text", "quote", "deliverable_name", "deliverable_format", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator("field", "kind", "priority", "req_type", "constraint_kind", mode="before")
    @classmethod
    def _default_when_null(cls, value: object, info: Any) -> object:
        if value is None:
            return cls.model_fields[info.field_name].default
        return value


class ChangeAnswer(BaseModel):
    changes: list[Change] = Field(default_factory=list)
    notes: str = ""

    @field_validator("changes", mode="before")
    @classmethod
    def _null_is_list(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("notes", mode="before")
    @classmethod
    def _null_is_empty(cls, value: object) -> object:
        return "" if value is None else value


REVISE_PROMPT = """You correct a list of items extracted from course or project documents, using a reviewer's issues.

Return {"changes": [...], "notes": "..."}. A change is one of:
- {"op": "add", "kind": "requirement" | "constraint" | "deliverable", "text": "<the item as one clear sentence>",
   "quote": "<the exact sentence from the document, copied character for character>", "priority", "req_type",
   "constraint_kind", "deliverable_name", "deliverable_format", "issue": <issue number>}
- {"op": "drop", "id": "R4", "issue": n}   (the item is not in the document, or is not an item at all)
- {"op": "set", "id": "R2", "field": "priority" | "req_type" | "kind" | "text", "value": "...", "issue": n}

Rules: fix only the listed issues; one change per problem. Never invent: an added item must quote a sentence that
is in the document. Do not add an item that is already listed under another wording. Setup steps that are not marked
or checked (install, clone, create an environment), background and reading instructions are not items: if an issue
asks to add one, skip it. If an issue is wrong, skip it and say so in notes. Marking criteria (E ids) are not yours
to change."""


def _next_id(rs: RequirementSet, prefix: str) -> str:
    nums = [int(m.group(1)) for _, it in items(rs) if (m := re.fullmatch(rf"{prefix}(\d+)", it.id))]
    return f"{prefix}{max(nums, default=0) + 1}"


def _source(inp: ExtractionInput, quote: str) -> tuple[SourceRef | None, float]:
    doc, m = find(inp, quote)
    if doc is None or m.block is None or m.status == "unverified":
        return None, 0.0
    return (SourceRef(doc_id=doc.doc_id, page=m.block.page, block_ids=[m.block.id], char_span=m.char_span,
                      quote=quote.strip(), folder=doc.folder),
            CONF_EXACT if m.status == "exact" else CONF_APPROXIMATE)


def _duplicate(rs: RequirementSet, kind: str, text: str, quote: str) -> str | None:
    """An item already saying this: same kind and similar text, or any kind quoting the same sentence (then the fix
    is to change that item's kind, not to add a second one)."""
    for k, it in items(rs):
        q = it.source_ref.quote if it.source_ref else None
        same_quote = bool(q and quote and (overlap(quote, q) >= 0.9 or overlap(q, quote) >= 0.9))
        if same_quote or (k == kind and jaccard(item_text(it), text) >= 0.8):
            return it.id
    for crit in rs.evaluation_criteria:      # a marking criterion is not also a requirement
        q = crit.source_ref.quote if crit.source_ref else None
        if (q and quote and overlap(quote, q) >= 0.9) or jaccard(crit.criterion, text) >= 0.8:  # not just containing it
            return crit.id
    return None


def _replace(rs: RequirementSet, item_id: str, new: Item | None) -> RequirementSet:
    def swap(lst: Sequence[Any]) -> list[Any]:
        out = []
        for it in lst:
            if it.id == item_id:
                if new is not None and type(new) is type(it):
                    out.append(new)
            else:
                out.append(it)
        return out
    return rs.model_copy(update={"requirements": swap(rs.requirements), "constraints": swap(rs.constraints),
                                 "deliverables": swap(rs.deliverables)})


def _append(rs: RequirementSet, kind: str, item: Item) -> RequirementSet:
    name = LISTS[kind][0]
    return rs.model_copy(update={name: [*getattr(rs, name), item]})


def _make(kind: str, item_id: str, text: str, ref: SourceRef, conf: float, ch: Change) -> Item:
    if kind == "requirement":
        return Requirement(id=item_id, text=text, priority=ch.priority, type=ch.req_type, source_ref=ref,
                           confidence=conf)
    if kind == "constraint":
        return Constraint(id=item_id, text=text, kind=ch.constraint_kind, source_ref=ref)
    return Deliverable(id=item_id, name=ch.deliverable_name.strip() or text, format=ch.deliverable_format.strip(),
                       source_ref=ref)


class ExtractionReviser:
    name = "extraction-patch"

    def __init__(self, role: str | None = None, max_tokens: int = 2500) -> None:
        self.role = role
        self.max_tokens = max_tokens

    @staticmethod
    def deterministic(rs: RequirementSet, critique: Critique) -> tuple[RequirementSet, list[str]]:
        """Programmatic issues that carry an exact fix (``set priority=should``) need no model."""
        notes = []
        for issue in critique.issues:
            m = FIX_RE.match(issue.fix_hint or "")
            if not m or issue.category != "FACTUAL":
                continue
            r = next((r for r in rs.requirements if r.id == issue.location), None)
            if r is None:
                continue
            fieldname, value = m.group(1), m.group(2)
            attr = "priority" if fieldname == "priority" else "type"
            if getattr(r, attr) != value:
                rs = _replace(rs, r.id, r.model_copy(update={attr: value}))
                notes.append(f"{r.id}: {attr} -> {value}")
        return rs, notes

    async def revise(self, output: RequirementSet, critique: Critique, history: Sequence[Attempt],
                     ctx: RefineContext, *, task_input: ExtractionInput | None = None,
                     strategy: Strategy = "targeted") -> Revision:
        assert task_input is not None
        rs, notes = self.deterministic(output, critique)
        applied = len(notes)
        rejected: list[str] = []
        flagged = {i.location for i in critique.issues if i.location is not None}
        fixed = {n.split(":", 1)[0] for n in notes}            # items a deterministic fix already corrected
        model_issues = [i for i in critique.issues if not FIX_RE.match(i.fix_hint or "")
                        and not (i.category == "FACTUAL" and i.location in fixed)]
        if model_issues and ctx.has_llm:
            try:
                answer = await self._ask(rs, model_issues, history, ctx, task_input, strategy)
            except Cancelled:
                raise
            except Exception as exc:
                log.info("extraction reviser: model failed", error=type(exc).__name__)
                answer = ChangeAnswer(notes=f"model failed: {type(exc).__name__}")
            omission_lists = {i.location for i in model_issues if i.category == "OMISSION" and i.location}
            for ch in answer.changes[:20]:
                rs, why = self._apply(rs, ch, task_input, flagged, omission_lists, strategy)
                if why:
                    rejected.append(f"{ch.op} {ch.id or ch.kind}: {why}")
                else:
                    applied += 1
                    notes.append(f"{ch.op} {ch.id or ch.kind}" + (f" ({ch.field}={ch.value})" if ch.op == "set"
                                                                  else ""))
            if answer.notes:
                notes.append(answer.notes[:300])
        if applied == 0:
            return Revision(output=output, notes=notes, applied=0, rejected=rejected)
        try:
            new = RequirementSet.model_validate(rs.model_dump())
        except Exception as exc:
            return Revision(output=output, applied=0, rejected=[*rejected, f"result breaks the contract: {exc}"[:300]])
        return Revision(output=new, notes=notes, applied=applied, rejected=rejected)

    async def _ask(self, rs: RequirementSet, issues: list[Issue], history: Sequence[Attempt], ctx: RefineContext,
                   inp: ExtractionInput, strategy: Strategy) -> ChangeAnswer:
        lines = "\n".join(f"{n}. [{i.severity} {i.category}] at {i.location}: {i.description}"
                          + (f" (evidence: \"{i.evidence[:240]}\")" if i.evidence else "")
                          + (f" (fix: {i.fix_hint[:160]})" if i.fix_hint else "")
                          for n, i in enumerate(issues, start=1))
        parts = [f"Issues:\n{lines}"]
        if notes := reflection_lines(history, ctx):
            parts.append(f"Notes from earlier attempts:\n{notes}")
        if strategy != "targeted":
            parts.append("Earlier fixes did not solve these issues: re-read the whole document and fix every item "
                         "that is wrong, not only the flagged ones.")
        if strategy == "widen" and inp.hits:
            parts.append("Sentences with requirement keywords (hints; some are not items):\n"
                         + "\n".join(f"- {h.text}" for h in inp.hits[:40]))
        parts.append(render_window(rs, [w for win in windows(inp, 10**9) for w in win], True))
        msgs = [Message(role="system", content=REVISE_PROMPT), Message(role="user", content="\n\n".join(parts))]
        return await ctx.generate(self.role or ctx.reviser_role, msgs, schema=ChangeAnswer,  # type: ignore[arg-type]
                                  max_tokens=self.max_tokens)

    @staticmethod
    def _apply(rs: RequirementSet, ch: Change, inp: ExtractionInput, flagged: set[str], omission_lists: set[str],
               strategy: Strategy) -> tuple[RequirementSet, str | None]:
        free = strategy != "targeted"
        if ch.op == "add":
            if not free and not omission_lists & set(LIST_KIND):
                return rs, "no issue asked for a new item"
            quote = ch.quote.strip()
            if not quote:
                return rs, "an added item needs a quote"
            ref, conf = _source(inp, quote)
            if ref is None:
                return rs, "its quote is not in the documents"
            text = ch.text.strip() or quote
            if not free and was_dropped(inp, quote):
                return rs, "removed by an earlier revision as not an item"
            if (dup := _duplicate(rs, ch.kind, text, quote)) is not None:
                return rs, f"already listed as {dup}" + (" (set its kind instead)" if not dup.startswith(
                    (LISTS[ch.kind][1], "E")) else "")
            item = _make(ch.kind, _next_id(rs, LISTS[ch.kind][1]), text, ref, conf, ch)
            return _append(rs, ch.kind, item), None
        target = next(((k, it) for k, it in items(rs) if it.id == ch.id.strip()), None)
        if target is None:
            return rs, "no such item"
        kind, it = target
        if not free and it.id not in flagged:
            return rs, "not flagged by an issue"
        if ch.op == "drop":
            inp.dropped.append(it.source_ref.quote if it.source_ref and it.source_ref.quote else item_text(it))
            return _replace(rs, it.id, None), None
        value = ch.value.strip()
        if ch.field == "priority" and isinstance(it, Requirement) and value in ("must", "should", "could"):
            return _replace(rs, it.id, it.model_copy(update={"priority": value})), None
        if ch.field == "req_type" and isinstance(it, Requirement) and value in ("functional", "non_functional"):
            return _replace(rs, it.id, it.model_copy(update={"type": value})), None
        if ch.field == "text" and value and not isinstance(it, Deliverable):
            return _replace(rs, it.id, it.model_copy(update={"text": value})), None
        if ch.field == "kind" and value in LISTS and value != kind:
            ref = it.source_ref
            if ref is None:
                return rs, "an item without a source cannot change kind"
            moved = _make(value, _next_id(rs, LISTS[value][1]), item_text(it), ref,
                          getattr(it, "confidence", CONF_EXACT), ch)
            return _append(_replace(rs, it.id, None), value, moved), None
        return rs, f"cannot set {ch.field or '?'} to {value!r}"


# ---------------------------------------------------------------------------------------------- setup


def extraction_setup(inp: ExtractionInput, *, judge: bool = True, stop: StopPolicy | None = None,
                     reflexion: bool = True) -> RefineSetup:
    return RefineSetup(artifact_type=ARTIFACT_TYPE, load=RequirementSet.model_validate_json,
                       critics=extraction_critics(inp, judge=judge), reviser=ExtractionReviser(), stop=stop,
                       task_input=inp, reflexion=reflexion, memory_key="document.extract", subject="requirements")


async def build_setup(task: TaskAssign, result: TaskResult, ctx: AgentContext) -> RefineSetup | None:
    """``Plugin.refiners["document.extract"]``: the document model travels in the agent's own result."""
    ref = next((r for r in result.artifact_refs if r.artifact_type == MODEL_TYPE), None)
    if ref is None or not any(r.artifact_type == ARTIFACT_TYPE for r in result.artifact_refs):
        return None
    model = DocumentModel.model_validate_json(await ctx.artifacts.get(ref, project_id=ctx.project_id))
    return extraction_setup(build_input(model))
