"""Evidence assembler (Sprint 10 item 10.1, plan D1): requirements <-> tasks <-> artifacts <-> reports.

Inputs: the newest ``requirement-set`` and ``task-graph`` (coverage matrix), the project's task table (handed over by
the recovery slot, plan T4: agents cannot read the task store) and every task's result artifacts. Output: one
:class:`Item` per requirement (R), constraint (C), deliverable (D), rubric criterion (E) and human change request
(H), each with short quoted evidence and its covering tasks:

- tests: the **newest round** of each test -> revise loop (Member 8), with the failing file;
- verification: Member 6's verdicts on the research claims a task relies on;
- docs: Member 9's ungrounded sentences and requirement coverage (document projects);
- deliverables: workspace files and documents that exist;
- constraints / change requests: violations found in the code's facts (imports, dependencies, language);
- the producer's own note (``CodeChangeSet.notes``) as a *claim*, cleaned of AI-directed lines (plan T9).

Without a task table (a unit test, or a Manager without the recovery slot) the plan's ids stand in for task ids.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from hmap.agents.coding.workspace import files_from_tar
from hmap.agents.docgen.inspect import inspect_files
from hmap.agents.docgen.model import Facts
from hmap.agents.research.sanitize import clean_text
from hmap.agents.review.model import DeliverableEv, Evidence, Item, TaskInfo, TestEv, VerificationEv
from hmap.core.contracts import (
    ArtifactRef,
    CodeChangeSet,
    DocBundle,
    RequirementSet,
    ResearchReport,
    TaskAssign,
    TaskGraph,
    TestReport,
    VerificationReport,
)
from hmap.core.runtime.base import AgentContext
from hmap.core.tracing import get_logger

log = get_logger("hmap.review.evidence")

SETTLED = {"COMPLETED", "FAILED", "DEAD_LETTERED", "CANCELLED", "BLOCKED"}
LANGUAGES = ("python", "java", "javascript", "typescript", "go", "rust", "c++", "c#", "kotlin", "ruby")
NEGATIVE = re.compile(r"\b(?:do\s+not|don'?t|never|must\s+not|should\s+not|no|without|avoid|instead\s+of)\s+"
                      r"(?:use\s+|using\s+|import\s+|rely\s+on\s+)?(?:the\s+|any\s+)?([A-Za-z][\w.+#-]*)", re.I)
POSITIVE_LANG = re.compile(r"\b(?:in|use|using|written\s+in|implement(?:ed)?\s+in)\s+(" +
                           "|".join(re.escape(x) for x in LANGUAGES) + r")\b", re.I)
STDLIB_ONLY = re.compile(r"\b(?:standard\s+library\s+only|only\s+the\s+standard\s+library|no\s+third[- ]party|"
                         r"no\s+external\s+(?:libraries|packages|dependencies))\b", re.I)
POSTFIX_NEG = re.compile(r"\b([A-Za-z][\w.+#-]*(?:\s+[A-Za-z][\w.+#-]*)?)\s+(?:are|is)\s+(?:not\s+allowed|"
                         r"forbidden|prohibited|not\s+permitted|banned)", re.I)
# category words a constraint may forbid -> the libraries that are one
CATEGORY = {
    "web framework": ("flask", "django", "fastapi", "starlette", "aiohttp", "tornado", "bottle", "pyramid", "sanic",
                      "falcon", "quart"),
    "networking framework": ("twisted", "tornado", "aiohttp", "trio", "curio", "gevent", "eventlet", "zmq", "pyzmq"),
    "framework": ("flask", "django", "fastapi", "twisted", "tornado", "aiohttp"),
}
# a constraint about how students work or hand in: nothing in the produced work can show it
PROCESS = re.compile(r"\b(deadline|due|submit|submission|submitted|hand[- ]in|portal|late|penalt\w*|groups?\s+of|"
                     r"team\s+of|individual(?:ly)?|pairs?|students?|plagiari\w*|attendance|week\s+\d+|"
                     r"\d{1,2}:\d{2})\b", re.I)
WORD_LIMIT = re.compile(r"\b(?:not\s+exceed|at\s+most|maximum\s+of|no\s+more\s+than|up\s+to|under)\s+"
                        r"(\d[\d,]*)\s+words\b", re.I)
CITATION = re.compile(r"\(([A-Z][\w'-]+(?:\s+et al\.)?(?:\s*(?:&|and)\s*[A-Z][\w'-]+)?),?\s+(\d{4}|n\.d\.)\)"
                      r"|\[\d+\]|\[C\d+(?:\.\w+)?\]")    # (Author, 2020), [2], or a claim id [C3]
NOT_A_THING = {"a", "an", "more", "other", "external", "third", "global", "magic", "hard", "longer", "less"}
DOC_WORDS = re.compile(r"\b(readme|documentation|docs?|report|manual|guide|write-?up|essay)\b", re.I)
TEST_WORDS = re.compile(r"\b(tests?|test\s+suite|unit\s+tests?)\b", re.I)
CODE_WORDS = re.compile(r"\b(source\s+code|code|program|implementation|script|application|app)\b", re.I)
HUMAN_ONLY = re.compile(r"\b(video|screencast|recording|presentation|slides? deck|viva|in[- ]person|poster|"
                        r"signature|signed|hand-?written|printed|demo session)\b", re.I)
NEEDS_PERSON = "needs a person"
FILE_NAME = re.compile(r"\b([\w-]+\.(?:py|md|txt|json|ya?ml|toml|sh|js|ts|java|c|cpp|h|pdf|docx|csv))\b", re.I)
NOTE_MAX = 400


def task_table(raw: Any) -> list[TaskInfo]:
    out = []
    for row in raw or []:
        try:
            out.append(TaskInfo.model_validate(row))
        except Exception:
            continue
    return out


@dataclass
class Bundle:
    items: list[Item]
    tasks: dict[str, TaskInfo]
    graph: TaskGraph | None
    requirements: RequirementSet | None
    mode: str
    plan_to_task: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    flagged: int = 0
    used: list[str] = field(default_factory=list)          # artifact ids read
    report_refs: list[ArtifactRef] = field(default_factory=list)
    changed_by: dict[str, str] = field(default_factory=dict)  # file -> the coding task (origin) that wrote it

    def descendants(self, task_id: str) -> list[str]:
        """Tasks that (transitively) depend on ``task_id``, in creation order."""
        out: list[str] = []
        todo = [task_id]
        while todo:
            cur = todo.pop()
            for t in self.tasks.values():
                if cur in t.depends_on and t.task_id not in out and not t.replaced:
                    out.append(t.task_id)
                    todo.append(t.task_id)
        order = list(self.tasks)
        return sorted(out, key=order.index)


class _Reader:
    """Cached artifact reads by id (newest version)."""

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx
        self.cache: dict[str, tuple[ArtifactRef, bytes] | None] = {}
        self.listing: list[ArtifactRef] | None = None

    async def get(self, artifact_id: str) -> tuple[ArtifactRef, bytes] | None:
        if artifact_id not in self.cache:
            ref = await self.ctx.artifacts.latest(artifact_id, project_id=self.ctx.project_id)
            self.cache[artifact_id] = (ref, await self.ctx.artifacts.get(ref, project_id=self.ctx.project_id)) \
                if ref is not None else None
        return self.cache[artifact_id]

    async def of_type(self, artifact_type: str) -> list[ArtifactRef]:
        if self.listing is None:
            self.listing = list(await self.ctx.artifacts.list(self.ctx.project_id))
        newest: dict[str, ArtifactRef] = {}
        for r in self.listing:
            if r.artifact_type == artifact_type and (r.artifact_id not in newest
                                                     or r.version > newest[r.artifact_id].version):
                newest[r.artifact_id] = r
        return sorted(newest.values(), key=lambda r: r.created_at)


def _newest(refs: Iterable[ArtifactRef], artifact_type: str) -> ArtifactRef | None:
    cands = [r for r in refs if r.artifact_type == artifact_type]
    return max(cands, key=lambda r: (r.created_at, r.version)) if cands else None


async def _model(reader: _Reader, aid: str, model: Any) -> tuple[ArtifactRef, Any] | None:
    got = await reader.get(aid)
    if got is None:
        return None
    try:
        return got[0], model.model_validate_json(got[1])
    except Exception:
        return None


def note_of(text: str) -> tuple[str, int]:
    cleaned, removed = clean_text(text or "")
    return cleaned[:NOTE_MAX], removed


async def assemble(task: TaskAssign, ctx: AgentContext) -> Bundle:
    reader = _Reader(ctx)
    tasks = {t.task_id: t for t in task_table(task.inputs.get("project_tasks"))}
    rs_ref = _newest(task.artifact_refs, "requirement-set") or \
        _newest(await reader.of_type("requirement-set"), "requirement-set")
    graph_refs = [*[r for r in task.artifact_refs if r.artifact_type == "task-graph"],
                  *await reader.of_type("task-graph")]
    rs: RequirementSet | None = None
    graph: TaskGraph | None = None
    notes: list[str] = []
    if rs_ref is not None:
        try:
            rs = RequirementSet.model_validate_json(await ctx.artifacts.get(rs_ref, project_id=ctx.project_id))
        except Exception as exc:
            notes.append(f"requirement set unreadable ({type(exc).__name__})")
    for ref in sorted(graph_refs, key=lambda r: r.created_at, reverse=True):
        try:
            g = TaskGraph.model_validate_json(await ctx.artifacts.get(ref, project_id=ctx.project_id))
        except Exception:
            continue
        if graph is None or g.version > graph.version:
            graph = g
    if not tasks and graph is not None:     # no task table: the plan's ids stand in (plan T4)
        notes.append("no task table from the Manager: plan task ids used for attribution")
        tasks = {p.id: TaskInfo(task_id=p.id, plan_task_id=p.id, capability=p.agent_capability, title=p.title,
                                requirement_ids=list(p.requirement_ids), depends_on=list(p.depends_on))
                 for p in graph.tasks}
    b = Bundle(items=[], tasks=tasks, graph=graph, requirements=rs, mode="software", notes=notes)
    b.mode = "software" if any(t.capability.startswith("code.") for t in tasks.values()) or not tasks else "document"
    live = [t for t in tasks.values() if not t.replaced]
    for t in live:
        if t.plan_task_id and t.plan_task_id not in b.plan_to_task:
            b.plan_to_task[t.plan_task_id] = t.task_id
    if rs is None:
        b.notes.append("no requirement set: nothing to review against")
        return b
    await _build(b, reader, task, ctx)
    b.used = sorted(a for a, v in reader.cache.items() if v is not None)
    return b


def _origin(t: TaskInfo, tasks: dict[str, TaskInfo]) -> str:
    """The plan task a revision / rerun / loop round descends from."""
    seen: set[str] = set()
    cur = t
    while cur.task_id not in seen:
        seen.add(cur.task_id)
        nxt = cur.original_task_id or cur.loop_origin or cur.parent_task_id
        if cur.plan_task_id or not nxt or nxt not in tasks:
            return cur.task_id
        cur = tasks[nxt]
    return cur.task_id


def _reqs_of(t: TaskInfo, tasks: dict[str, TaskInfo]) -> list[str]:
    o = tasks.get(_origin(t, tasks), t)
    return list(dict.fromkeys([*t.requirement_ids, *o.requirement_ids]))


async def _build(b: Bundle, reader: _Reader, task: TaskAssign, ctx: AgentContext) -> None:
    assert b.requirements is not None
    rs = b.requirements
    tasks = b.tasks
    coverage = dict(b.graph.coverage_matrix) if b.graph else {}
    # requirement -> covering tasks (Manager ids), revisions included
    by_origin: dict[str, list[TaskInfo]] = {}
    for t in tasks.values():
        if not t.replaced and t.capability != "review.final":
            by_origin.setdefault(_origin(t, tasks), []).append(t)

    def covering(rid: str) -> list[str]:
        plan_ids = coverage.get(rid, [])
        out = [b.plan_to_task.get(p, p) for p in plan_ids]
        out += [t.task_id for t in tasks.values() if rid in t.requirement_ids and t.capability != "review.final"
                and not t.replaced and t.task_id not in out]
        return [o for o in out if o in tasks and tasks[o].capability != "review.final"] or \
            [o for o in out if o not in tasks]

    items: dict[str, Item] = {}
    for r in rs.requirements:
        items[r.id] = Item(id=r.id, kind="requirement", text=r.text, priority=r.priority, covering=covering(r.id),
                           mode=b.mode)
    for c in rs.constraints:
        fixer = "code." if b.mode == "software" else "docs."
        cov = covering(c.id) or [t.task_id for t in tasks.values() if t.capability.startswith(fixer)
                                 and t.plan_task_id and not t.replaced]
        items[c.id] = Item(id=c.id, kind="constraint", text=c.text, covering=cov, mode=b.mode)
    for d in rs.deliverables:
        items[d.id] = Item(id=d.id, kind="deliverable", text=f"{d.name} ({d.format})" if d.format else d.name,
                           covering=covering(d.id) or _deliverable_owner(d.name, tasks), mode=b.mode)
    for e in rs.evaluation_criteria:
        items[e.id] = Item(id=e.id, kind="criterion", text=e.criterion, max_marks=e.max_marks, priority="should",
                           rubric_levels=[lv.model_dump() for lv in e.rubric_levels], mode=b.mode)
    n = 0
    for t in tasks.values():                       # human change requests (Member 3's "Change plan…" feedback)
        if t.capability == "plan.replan" and t.feedback.strip() and t.recovery_round is None:
            n += 1
            items[f"H{n}"] = Item(id=f"H{n}", kind="change", text=t.feedback.strip()[:400],
                                  covering=[x.task_id for x in tasks.values() if x.capability.startswith("code.")
                                            and not x.replaced], mode=b.mode)
    for extra in task.inputs.get("change_requests") or []:
        if isinstance(extra, str) and extra.strip():
            n += 1
            items[f"H{n}"] = Item(id=f"H{n}", kind="change", text=extra.strip()[:400],
                                  covering=[x.task_id for x in tasks.values() if x.capability.startswith("code.")
                                            and not x.replaced], mode=b.mode)

    # ---- per task family: newest results
    files: dict[str, str] = {}
    head = await reader.get(f"wsh-{ctx.project_id}")
    if head is not None:
        try:
            files = files_from_tar(head[1])
        except Exception:
            b.notes.append("workspace head unreadable")
    facts: Facts | None = inspect_files(files, "project") if files else None
    changed_by: dict[str, str] = {}               # file -> coding origin task
    notes_by: dict[str, str] = {}
    stub_tasks: set[str] = set()
    tests_by_req: dict[str, list[TestEv]] = {}
    verif_by_req: dict[str, list[VerificationEv]] = {}
    docs_bundle: DocBundle | None = None
    docs_task: str | None = None
    report_text = ""
    report_parts: list[tuple[str, str]] = []                 # (phase, text) newest per docs step
    doc_coverage: dict[str, str] = {}

    for origin, family in by_origin.items():
        family.sort(key=lambda t: t.created_at)
        cap = tasks[origin].capability if origin in tasks else family[0].capability
        results = [a for t in family for a in t.results]
        # stub output: every result artifact of the family was written by a stub agent
        refs = [hit[0] for a in results if (hit := await reader.get(a)) is not None]
        if refs and all(r.created_by.startswith("stub-") for r in refs):
            stub_tasks.add(origin)
            stub_tasks.update(t.task_id for t in family)
            continue
        if cap.startswith("code."):
            for t in family:
                for a in t.results:
                    got = await _model(reader, a, CodeChangeSet)
                    if got is None:
                        continue
                    cs = got[1]
                    for f in cs.files_changed:
                        changed_by[f] = origin
                    if cs.notes:
                        note, removed = note_of(cs.notes)
                        b.flagged += removed
                        notes_by[origin] = note
        elif cap == "test.run":
            await _tests(b, reader, family, origin, tests_by_req)
        elif cap == "verify.claims":
            await _verification(b, reader, family, origin, verif_by_req)
        elif cap.startswith("docs."):
            # newest bundle of each docs step; a report project has several (outline, sections, the document):
            # their coverage is merged ("shown" anywhere wins), the software README / report is the newest one
            for t in reversed(family):
                bundle = None
                for a in t.results:
                    got = await _model(reader, a, DocBundle)
                    if got is not None:
                        bundle = got[1]
                        b.report_refs.append(got[0])
                if bundle is None:
                    continue
                if docs_bundle is None or t.created_at >= (tasks[docs_task].created_at if docs_task else ""):
                    docs_bundle, docs_task = bundle, t.task_id
                _merge_coverage(doc_coverage, await _doc_coverage(reader, t))
                if bundle.report_sections_ref is not None:
                    got_r = await reader.get(bundle.report_sections_ref.artifact_id)
                    if got_r:
                        phase = tasks[origin].phase if origin in tasks else ""
                        report_parts.append((phase, got_r[1].decode("utf-8", "replace")))
                break
    whole = [txt for ph, txt in report_parts if ph == "document"]
    report_text = whole[0] if whole else "\n\n".join(txt for _, txt in report_parts)
    # ---- fill the items
    used_ungrounded = False
    for item in items.values():
        ev = Evidence()
        cov = list(item.covering)
        cov_origins = {_origin(tasks[c], tasks) if c in tasks else c for c in cov}
        ev.stub = bool(cov_origins) and cov_origins <= stub_tasks
        if item.kind == "requirement":
            ev.tests = tests_by_req.get(item.id, [])
            ev.verification = verif_by_req.get(item.id, [])
            if b.mode == "document" or item.id in doc_coverage:
                ev.doc_status = doc_coverage.get(item.id)
            shown = shown_in_text(item.text, report_text) if b.mode == "document" and report_text and \
                ev.doc_status != "shown" else None
            if shown:
                ev.doc_status = "shown"
                ev.facts.append(shown)
        if item.kind == "deliverable":
            ev.deliverables = [_deliverable(item.text, files, docs_bundle)]
        if item.kind == "constraint" and PROCESS.search(item.text) and not _technical(item.text):
            ev.deliverables = [DeliverableEv(name=item.text, present=None, where=NEEDS_PERSON)]
        elif item.kind in ("constraint", "change"):
            if facts is not None and b.mode == "software":
                ev.violations, ev.facts = violations(item.text, facts)
            if report_text:
                bad, good = document_checks(item.text, report_text)
                ev.violations += bad
                ev.facts += good
        if docs_bundle is not None and docs_bundle.accuracy_report.ungrounded_claims and \
                (docs_task in cov or (docs_task is not None and docs_task in cov_origins) or
                 (item.kind == "deliverable" and DOC_WORDS.search(item.text))):
            ev.doc_ungrounded = list(docs_bundle.accuracy_report.ungrounded_claims)[:10]
            used_ungrounded = True
        ev.producer_note = " ".join(notes_by[o] for o in cov_origins if o in notes_by)[:NOTE_MAX]
        ev.facts += [f"{t.name}: {t.status}" + (f" ({t.module})" if t.module else "") for t in ev.tests][:5]
        item.evidence = ev
    if docs_bundle is not None and docs_bundle.accuracy_report.ungrounded_claims and not used_ungrounded:
        items["DOCS"] = Item(id="DOCS", kind="deliverable", text="The documentation is accurate (every technical "
                             "claim is supported by the code)", covering=[docs_task] if docs_task else [],
                             evidence=Evidence(doc_ungrounded=list(docs_bundle.accuracy_report.ungrounded_claims)[:10],
                                               deliverables=[DeliverableEv(name="documentation", present=True)]),
                             mode=b.mode)
    b.items = list(items.values())
    if facts is not None:
        b.notes.append(f"workspace: {len(files)} file(s), language {facts.language}")
    b.changed_by = changed_by


async def _tests(b: Bundle, reader: _Reader, family: list[TaskInfo], origin: str,
                 out: dict[str, list[TestEv]]) -> None:
    tasks = b.tasks
    newest: tuple[TaskInfo, TestReport, dict[str, Any]] | None = None
    for t in family:
        for a in t.results:
            got = await _model(reader, a, TestReport)
            if got is None:
                continue
            trace: dict[str, Any] = {}
            tr = await reader.get(f"tt-{t.task_id}")
            if tr is not None:
                try:
                    trace = json.loads(tr[1])
                except Exception:
                    trace = {}
            rnd = int((trace.get("loop") or {}).get("round") or 0)
            if newest is None or (rnd, t.created_at) >= (int((newest[2].get("loop") or {}).get("round") or 0),
                                                         newest[0].created_at):
                newest = (t, got[1], trace)
            b.report_refs.append(got[0])
    if newest is None:
        return
    t, report, trace = newest
    coding = str(trace.get("coding_task_id") or "")
    covers = _reqs_of(t, tasks)
    if coding and coding in tasks:
        covers += [r for r in _reqs_of(tasks[coding], tasks) if r not in covers]
    real = [f for f in trace.get("failures") or [] if f.get("category") != "LINT" and not f.get("generated")]
    fails = real or [f.model_dump() for f in report.failures if f.category != "LINT"]
    flaky = bool(trace.get("flaky")) and not real
    timeout = bool(fails) and all(f.get("category") == "TIMEOUT" for f in fails)
    status = "passed" if report.passed else "timeout" if timeout else "failed"
    pending = any(x.capability in ("test.run", "code.revise") and x.state not in SETTLED and not x.replaced
                  and _origin(x, tasks) in (origin, coding) for x in tasks.values())
    first = fails[0] if fails else {}
    ev = TestEv(name=f"tests: {tasks[origin].title or origin}" if origin in tasks else "tests", status=status,
                covers=covers, module=next((f.get("file") for f in fails if f.get("file")), None), task_id=t.task_id,
                coding_task_id=coding or None, flaky=flaky,
                detail=str(first.get("message") or "")[:200], round=int((trace.get("loop") or {}).get("round") or 0),
                pending=pending)
    for rid in covers:
        out.setdefault(rid, []).append(ev)


async def _verification(b: Bundle, reader: _Reader, family: list[TaskInfo], origin: str,
                        out: dict[str, list[VerificationEv]]) -> None:
    tasks = b.tasks
    for t in reversed(family):
        for a in t.results:
            got = await _model(reader, a, VerificationReport)
            if got is None:
                continue
            report: VerificationReport = got[1]
            b.report_refs.append(got[0])
            texts: dict[str, str] = {}
            if report.research_report_ref is not None:
                rr = await _model(reader, report.research_report_ref.artifact_id, ResearchReport)
                if rr is not None:
                    texts = {c.id: c.text for c in rr[1].claims}
            reqs = _reqs_of(t, tasks)
            for dep in tasks[origin].depends_on if origin in tasks else []:
                if dep in tasks and tasks[dep].capability.startswith("research."):
                    reqs += [r for r in _reqs_of(tasks[dep], tasks) if r not in reqs]
            for v in report.claim_verdicts:
                verdict = {"VERIFIED": "supported", "CONFLICTING": "contradicted"}.get(v.verdict, "unsupported")
                text, _ = note_of(texts.get(v.claim_id, v.claim_id))
                for rid in reqs:
                    out.setdefault(rid, []).append(VerificationEv(claim=text[:200] or v.claim_id, verdict=verdict,
                                                                  task_id=t.task_id))
            return


def _merge_coverage(into: dict[str, str], new: dict[str, str]) -> None:
    rank = {"shown": 2, "conflict": 1, "not shown": 0}
    for rid, status in new.items():
        if rank.get(status, 0) >= rank.get(into.get(rid, ""), -1):
            into[rid] = status


SECTION_WORDS = re.compile(r"\b(conclusion|introduction|summary|abstract|references|bibliography|recommendation)s?\b",
                           re.I)


def shown_in_text(requirement: str, text: str) -> str | None:
    """Requirements a report satisfies by its form, read from the text itself: a named section ("End with a
    conclusion") or citations ("Every claim must be supported by a citation")."""
    headings = [h.strip().lower() for h in re.findall(r"^#{1,6}\s+(.+)$", text, re.M)]
    for m in SECTION_WORDS.finditer(requirement):
        word = m.group(1).lower()
        if any(word in h for h in headings):
            return f"the document has a '{word}' section"
    if re.search(r"\b(cite|cited|citation|citations|source|sources|references?)\b", requirement, re.I):
        n = len(CITATION.findall(text))
        if n:
            return f"the document has {n} citation(s)"
    return None


async def _doc_coverage(reader: _Reader, t: TaskInfo) -> dict[str, str]:
    got = await reader.get(f"dtr-{t.task_id}")
    if got is None:
        return {}
    try:
        trace = json.loads(got[1])
    except Exception:
        return {}
    out: dict[str, str] = {}
    for row in trace.get("coverage") or []:
        rid, status = str(row.get("req_id") or ""), str(row.get("status") or "")
        if rid and status:
            # several sections may answer one requirement: "shown" anywhere wins, then "conflict"
            prev = out.get(rid)
            if prev != "shown" and (status == "shown" or prev is None or status == "conflict"):
                out[rid] = status
    return out


def _deliverable_owner(name: str, tasks: dict[str, TaskInfo]) -> list[str]:
    def first(pred: Any) -> list[str]:
        return [t.task_id for t in tasks.values() if pred(t.capability) and not t.replaced and t.plan_task_id][:1]
    if DOC_WORDS.search(name):
        return first(lambda c: c.startswith("docs."))
    if TEST_WORDS.search(name):
        return first(lambda c: c == "test.run")
    return first(lambda c: c.startswith("code.")) or first(lambda c: c.startswith("docs."))


def _deliverable(name: str, files: dict[str, str], bundle: DocBundle | None) -> DeliverableEv:
    if HUMAN_ONLY.search(name) or (PROCESS.search(name) and not FILE_NAME.search(name)):
        # no agent can make a video, give a presentation or hand the work in: a person's part
        return DeliverableEv(name=name, present=None, where=NEEDS_PERSON)
    lower = {f.lower(): f for f in files}
    m = FILE_NAME.search(name)
    if m:
        want = m.group(1).lower()
        hit = next((orig for low, orig in lower.items() if low == want or low.endswith("/" + want)), None)
        if hit:
            return DeliverableEv(name=name, present=True, where=hit)
        if want.startswith("readme") and bundle is not None and bundle.readme_ref is not None:
            return DeliverableEv(name=name, present=True, where="README in the documentation bundle")
        return DeliverableEv(name=name, present=False if files else None)
    if re.search(r"\breadme\b", name, re.I):
        if any(f.lower().endswith("readme.md") for f in files) or (bundle is not None and bundle.readme_ref):
            return DeliverableEv(name=name, present=True, where="README")
        return DeliverableEv(name=name, present=False if (files or bundle) else None)
    if DOC_WORDS.search(name):
        if bundle is not None and (bundle.report_sections_ref or bundle.readme_ref):
            return DeliverableEv(name=name, present=True, where="the documentation bundle")
        return DeliverableEv(name=name, present=False if (files or bundle) else None)
    if TEST_WORDS.search(name):
        tests = [f for f in files if re.search(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$)", f)]
        if tests:
            return DeliverableEv(name=name, present=True, where=f"{len(tests)} test file(s)")
        return DeliverableEv(name=name, present=False if files else None)
    if CODE_WORDS.search(name):
        code = [f for f in files if f.endswith((".py", ".js", ".ts", ".java", ".c", ".cpp", ".go", ".rs"))]
        if code:
            return DeliverableEv(name=name, present=True, where=f"{len(code)} source file(s)")
        return DeliverableEv(name=name, present=False if files else None)
    return DeliverableEv(name=name, present=None)


def _technical(text: str) -> bool:
    """A constraint that names code things (a language, a library, a port) is checked, even if it mentions a week."""
    return bool(NEGATIVE.search(text) or POSITIVE_LANG.search(text) or STDLIB_ONLY.search(text) or
                POSTFIX_NEG.search(text) or re.search(r"\bport\b|\blibrar|\bmodule\b|\bframework", text, re.I))


def document_checks(text: str, report: str) -> tuple[list[str], list[str]]:
    """Word limits and citations of a written document."""
    bad: list[str] = []
    good: list[str] = []
    words = len(re.findall(r"[A-Za-z0-9][\w'-]*", re.sub(r"```.*?```", " ", report, flags=re.S)))
    if m := WORD_LIMIT.search(text):
        limit = int(m.group(1).replace(",", ""))
        (bad if words > limit else good).append(f"the document has {words} words (limit {limit})")
    if re.search(r"\b(cite|citation|references?|sources?|APA|IEEE|Harvard)\b", text):
        n = len(CITATION.findall(report))
        good.append(f"the document has {n} citation(s)")
    return bad, good


def violations(text: str, facts: Facts) -> tuple[list[str], list[str]]:
    """Constraint / change-request text against the code's facts: (violations, supporting facts)."""
    used: dict[str, list[str]] = {}
    for path, mod in facts.modules.items():
        if "/test" in f"/{path}" or path.startswith("tests/"):
            continue
        for name in mod.imports:
            used.setdefault(name.lower(), []).append(path)
    deps = {d.lower() for d in facts.dependencies}
    techs = {t.lower() for t in facts.technologies}
    bad: list[str] = []
    good: list[str] = []
    third = sorted(d for d in deps if d not in ("pytest",))
    good.append("the code imports: " + ", ".join(sorted(used)[:25]) if used else "the code imports nothing")
    good.append("declared dependencies: " + (", ".join(third[:10]) or "none"))
    lowered = text.lower()
    for cat, libs in CATEGORY.items():
        if re.search(rf"\b(?:no|not|without|don'?t|do not|never|avoid)\b[^.;]*\b{cat}s?\b|\b{cat}s?\b[^.;]*\b"
                     rf"(?:not allowed|forbidden|prohibited|not permitted|banned)", lowered):
            hit = sorted({lib for lib in libs if lib in used or lib in deps})
            if hit:
                bad.append(f"uses a {cat}: {', '.join(hit)}")
            else:
                good.append(f"no {cat} is used")
            break
    names = [m.group(1) for m in NEGATIVE.finditer(text)]
    for m in POSTFIX_NEG.finditer(text):
        names += m.group(1).split()
    for raw in names:
        word = raw.lower().rstrip(".,;:")
        if word in NOT_A_THING or len(word) < 2 or word in ("web", "networking", "framework", "frameworks"):
            continue
        if word in used:
            bad.append(f"uses {word}: {', '.join(sorted(used[word])[:3])} import(s) it")
        elif word in deps or word in techs:
            bad.append(f"uses {word} (declared dependency)")
        else:
            good.append(f"{word} is not used by the code")
    if m2 := POSITIVE_LANG.search(text):
        lang = m2.group(1).lower()
        if facts.language and facts.language.lower() != lang and facts.files:
            bad.append(f"the code is {facts.language}, not {lang}")
        elif facts.files:
            good.append(f"the code is {facts.language}")
    if STDLIB_ONLY.search(text):
        if third:
            bad.append("third-party dependencies: " + ", ".join(third[:5]))
        else:
            good.append("no third-party dependencies")
    return bad, good
