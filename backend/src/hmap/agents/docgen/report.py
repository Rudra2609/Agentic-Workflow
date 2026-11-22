"""Report sections mapped to the required deliverables (Sprint 9 item 9.8, plan D1, D10).

**software** mode (there is code): one section set per document deliverable of the ``RequirementSet`` (Member 3's
``DOC_DELIVERABLE`` decides which deliverables are documents): overview, requirements and where the code meets them,
design, implementation, testing (from the ``TestReport``), how to run, limitations. Each requirement is mapped to the
evidence that shows it (routes, modules, tests sharing its words); a requirement with no evidence is listed as
"not shown", never claimed.

**document** mode (a report / essay project: the outline, the sections and the final document are all
``docs.generate`` steps): the text is built only from the research report's claims that Member 6 marked VERIFIED,
each sentence citing its claim (``[C3]``) and the sources listed at the end. Member 9 does not re-verify research;
without a verification report the claims are used but marked unverified. With a model, ``reasoner`` turns each
section's claims into a paragraph; every sentence must keep a citation to an allowed claim or it is removed.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from hmap.agents.docgen.architecture import Architecture, code_modules
from hmap.agents.docgen.model import Claim, Facts
from hmap.agents.docgen.readme import install_commands, run_commands, test_commands
from hmap.agents.docgen.summarize import UNTRUSTED, Summaries
from hmap.agents.planning.templates import DOC_DELIVERABLE
from hmap.core.contracts import RequirementSet
from hmap.core.contracts.domain import ResearchReport, VerificationReport
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.docgen.report")

STOP = {"the", "and", "for", "with", "that", "this", "must", "should", "shall", "will", "can", "each", "every", "from",
        "into", "when", "which", "have", "has", "are", "is", "be", "a", "an", "to", "of", "in", "on", "it", "its",
        "by", "or", "as", "at", "use", "using", "user", "users", "system", "program", "application", "project"}
CITE = re.compile(r"\[(C[\w-]+)\]")


@dataclass
class ReportOut:
    markdown: str
    coverage: list[dict[str, Any]] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)          # document mode: one CITATION claim per sentence
    model_calls: int = 0
    tokens: int = 0
    notes: list[str] = field(default_factory=list)


def _words(text: str) -> set[str]:
    return {w for w in (x.lower() for x in re.findall(r"[A-Za-z][A-Za-z0-9]+", text)) if len(w) > 2} - STOP


def doc_deliverables(rs: RequirementSet | None) -> list[str]:
    if rs is None:
        return []
    return [d.name for d in rs.deliverables if DOC_DELIVERABLE.search(f"{d.name} {d.format}")]


def requirement_evidence(text: str, facts: Facts) -> list[str]:
    """Code that shares words with the requirement: endpoints, modules, functions, tests (best 4)."""
    want = _words(text)
    if not want:
        return []
    scored: list[tuple[int, str]] = []
    for r in facts.routes:
        n = len(want & _words(f"{r.path} {r.function} {r.doc}"))
        if n:
            scored.append((n + 1, f"endpoint {r.method} {r.path}"))
    for path, mod in code_modules(facts).items():
        for s in mod.symbols:
            n = len(want & _words(f"{s.name.replace('_', ' ')} {s.doc}"))
            if n >= 1:
                scored.append((n, f"`{path}::{s.name if not s.parent else s.parent + '.' + s.name}`"))
    for t in facts.tests:
        n = len(want & _words(t.replace("_", " ").replace("/", " ")))
        if n:
            scored.append((n, f"test `{t}`"))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: list[str] = []
    for _, e in scored:
        if e not in out:
            out.append(e)
    return out[:4]


def software(facts: Facts, arch: Architecture, summaries: Summaries | None, rs: RequirementSet | None,
             test_report: dict[str, Any] | None, title: str) -> ReportOut:
    names = doc_deliverables(rs) or [title]
    out = ReportOut(markdown="")
    reqs = list(rs.requirements) if rs else []
    rows: list[dict[str, Any]] = []
    for r in reqs:
        ev = requirement_evidence(r.text, facts)
        conflict = [f"the code uses port {', '.join(map(str, facts.ports)) or 'none'}, not {p}"
                    for p in re.findall(r"\bport\s+(\d{2,5})\b", r.text, re.I) if int(p) not in facts.ports]
        rows.append({"req_id": r.id, "text": r.text, "evidence": ev, "conflict": conflict, "section": "Requirements",
                     "status": "conflict" if conflict else "shown" if ev else "not shown"})
    out.coverage = rows
    body: list[str] = []
    body += ["## Overview", "", summaries.repo if summaries else "", ""]
    if rows:
        body += ["## Requirements and where they are met", "", "| Requirement | Evidence in the code |", "|---|---|"]
        for row in rows:
            shown = "; ".join(row["conflict"]) or ("; ".join(row["evidence"]) if row["evidence"] else
                                                   "not shown in the code")
            quoted = str(row["text"])[:160].replace("|", "/").replace("\u201c", "'").replace("\u201d", "'")
            body.append(f"| {row['req_id']}: \u201c{quoted}\u201d | {shown} |")     # a quote, not a claim
        body.append("")
    body += ["## Design", "", "| Component | Modules | What it is |", "|---|---|---|"]
    body += [f"| `{c.label}` | {len(c.modules)} | {c.doc.replace('|', '/')} |" for c in arch.components[:25]]
    body += ["", "## Implementation", ""]
    for path, about in list((summaries.files if summaries else {}).items())[:25]:
        body.append(f"- `{path}`: {about}")
    body += ["", "## Testing", ""]
    if test_report:
        stages = test_report.get("stages") or {}
        body.append("Result of the testing step: **" + ("passed" if test_report.get("passed") else "failed") + "**.")
        body += ["", "| Stage | Status |", "|---|---|"]
        body += [f"| {name} | {(s or {}).get('status', '')} |" for name, s in stages.items()]
        if test_report.get("coverage") is not None:
            body += ["", f"Line coverage: {test_report['coverage']} %."]
        fails = test_report.get("failures") or []
        if fails:
            body += ["", f"{len(fails)} failure(s), for example: {str(fails[0].get('message', ''))[:200]}"]
        body.append("")
    tests = test_commands(facts)
    body.append(f"{len(facts.tests)} test file(s) with {facts.test_functions} test functions." if facts.tests
                else "The code has no test files.")
    if tests:
        body += ["", "```bash", *tests, "```"]
    run = install_commands(facts) + run_commands(facts)
    if run:
        body += ["", "## How to run", "", "```bash", *run, "```"]
    missing = [row for row in rows if row["status"] != "shown"]
    if missing or (test_report and not test_report.get("passed")):
        body += ["", "## Limitations", ""]
        body += [f"- {row['req_id']}: " + ("; ".join(row["conflict"]) if row["conflict"] else
                                            "not shown in the code yet") + "." for row in missing]
        if test_report and not test_report.get("passed"):
            body.append("- The tests do not all pass yet.")
    text = []
    for name in names:
        text += [f"# {name}", "", *body, ""]
    out.markdown = "\n".join(text).rstrip() + "\n"
    return out


class _Paragraph(BaseModel):
    text: str = Field(max_length=2500)


@dataclass
class _Allowed:
    claims: dict[str, str]                  # claim id -> text
    sources: dict[str, list[str]]           # claim id -> urls
    verified: bool


def allowed_claims(research: ResearchReport | None, verification: VerificationReport | None) -> _Allowed:
    if research is None:
        return _Allowed({}, {}, False)
    ev_url = {e.id: e.url for e in research.evidence}
    ok = None
    if verification is not None:
        ok = {v.claim_id for v in verification.claim_verdicts if v.verdict == "VERIFIED"}
    claims = {c.id: c.text for c in research.claims if ok is None or c.id in ok}
    sources = {c.id: sorted({ev_url[e] for e in c.evidence_ids if e in ev_url}) for c in research.claims
               if c.id in claims}
    return _Allowed(claims, sources, verification is not None)


def _sections(rs: RequirementSet | None, allowed: _Allowed, objective: str) -> list[tuple[str, list[str]]]:
    """One section per requirement (its title from the requirement), the claims sharing most words with it."""
    reqs = [(r.id, r.text) for r in (rs.requirements if rs else [])] or [("R1", objective)]
    used: set[str] = set()
    out = []
    for rid, text in reqs:
        want = _words(text)
        ranked = sorted(allowed.claims, key=lambda c: (-len(want & _words(allowed.claims[c])), c))
        picked = [c for c in ranked if len(want & _words(allowed.claims[c])) > 0][:6]
        used |= set(picked)
        out.append((f"{rid}: {text[:90]}", picked))
    rest = [c for c in allowed.claims if c not in used]
    if rest:
        out.append(("Further findings", rest[:10]))
    return out


async def document(llm: LLMClient | None, rs: RequirementSet | None, research: ResearchReport | None,
                   verification: VerificationReport | None, objective: str, step: str, title: str) -> ReportOut:
    allowed = allowed_claims(research, verification)
    out = ReportOut(markdown="")
    if not allowed.claims:
        out.notes.append("no research claims to write from" if research is None else
                         "no claim was verified: nothing may be written as a finding")
    if research is not None and not allowed.verified:
        out.notes.append("no verification report: claims used as found by the research step (unverified)")
    sections = _sections(rs, allowed, objective)
    names = doc_deliverables(rs) or [title]
    lines = [f"# {names[0]}", ""]
    if step == "design":                                   # the outline step: structure + which claim goes where
        lines += ["Outline: one section per requirement, with the verified findings it will use.", ""]
        for head, ids in sections:
            lines += [f"## {head}", ""]
            lines += [f"- {allowed.claims[c]} [{c}]" for c in ids] or ["- (no verified finding yet)"]
            lines.append("")
            out.coverage.append({"req_id": head.split(":")[0], "section": head, "claims": ids,
                                 "status": "shown" if ids else "not shown"})
    else:
        for head, ids in sections:
            lines += [f"## {head}", ""]
            out.coverage.append({"req_id": head.split(":")[0], "section": head, "claims": ids,
                                 "status": "shown" if ids else "not shown"})
            if not ids:
                lines += ["No verified finding covers this part yet.", ""]
                continue
            para = await _paragraph(llm, head, ids, allowed, out)
            lines += [para, ""]
    refs = sorted({u for ids in (s[1] for s in sections) for c in ids for u in allowed.sources.get(c, [])})
    if refs:
        lines += ["## Sources", ""] + [f"{n}. {u}" for n, u in enumerate(refs, 1)] + [""]
    md = "\n".join(lines).rstrip() + "\n"
    md, out.claims = ground_citations(md, allowed)
    out.markdown = md
    return out


async def _paragraph(llm: LLMClient | None, head: str, ids: list[str], allowed: _Allowed, out: ReportOut) -> str:
    plain = " ".join(f"{allowed.claims[c].rstrip('.')}. [{c}]" for c in ids)
    if llm is None:
        return plain
    facts = "\n".join(f"[{c}] {allowed.claims[c]}" for c in ids)
    prompt = (f"Section: {head}\nFindings (the only things you may state):\n{facts}\n\nWrite one paragraph for "
              "this section of the report. Every sentence must end with the id of the finding it states, like "
              "[C1]. Do not add facts, numbers or names that are not in the findings.")
    try:
        resp = await llm.generate("reasoner", [{"role": "system", "content": "You write report sections. "
                                                + UNTRUSTED.replace("code and its comments", "findings")},
                                               {"role": "user", "content": prompt}],
                                  schema=_Paragraph, max_tokens=900, temperature=0.0, seed=7)
    except Exception as exc:
        log.info("report prose skipped", error=type(exc).__name__)
        return plain
    out.model_calls += 1
    out.tokens += resp.usage.input_tokens + resp.usage.output_tokens
    parsed = resp.parsed if isinstance(resp.parsed, _Paragraph) else None
    return " ".join(parsed.text.split()) if parsed and parsed.text.strip() else plain


def ground_citations(md: str, allowed: _Allowed) -> tuple[str, list[Claim]]:
    """Document mode grounding: every sentence of a section paragraph must cite an allowed claim; the others are
    removed (and reported as ungrounded)."""
    claims: list[Claim] = []
    lines = md.split("\n")
    for i, line in enumerate(lines):
        if not line.strip() or line.startswith(("#", "|", "Outline:")) or re.match(r"\d+\. http", line) \
                or line.startswith("No verified finding"):
            continue
        prefix = "- " if line.startswith("- ") else ""
        kept = []
        for sentence in re.split(r"(?<=[.!?\]])\s+(?=[A-Z(\"])", line.removeprefix(prefix)):
            ids = CITE.findall(sentence)
            good = [c for c in ids if c in allowed.claims]
            ok = bool(good) and len(good) == len(ids)
            verdict = ("grounded" if allowed.verified else "unverified") if ok else "ungrounded"
            why = ("cites " + ", ".join(good) + (" (verified)" if allowed.verified else " (not verified yet)")) if ok \
                else ("cites no finding" if not ids else f"cites unknown finding(s) {sorted(set(ids) - set(good))}")
            claims.append(Claim(kind="CITATION", text=sentence[:200], verdict=verdict, why=why,
                                doc="report", sentence=sentence[:400], line=i + 1))
            if ok:
                kept.append(sentence)
        lines[i] = (prefix + " ".join(kept)) if kept else ""
    return "\n".join(lines), claims
