"""Synthesis with citations (Sprint 5 item 5.9, plan D11).

``reasoner`` writes short claims per sub-question, each citing evidence ids (schema). Then the **citation check**
(code, always on) keeps only claims that cite at least one existing piece of evidence for the same sub-question
and share at least one content word with a cited quote; everything else is dropped and listed in the trace. Without
a model each piece of evidence becomes a claim quoting it (honest, if dull).

With the project's "Check and improve results" switch (``task.refine``) the agent then runs Member 4's refinement
on the report (:func:`refine_setup`): the same citation check as a ``ProgrammaticCritic`` + a rubric judge for
completeness, and a ``TargetedReviser`` that may only change ``/claims`` and ``/summary_markdown`` (evidence and
sources are facts, never rewritten).
"""

from collections.abc import Sequence

from pydantic import BaseModel, Field

from hmap.agents.research import quotes, sanitize
from hmap.agents.research.model import EvidenceDraft
from hmap.core.contracts import ResearchReport
from hmap.core.contracts.domain import Claim, Issue, SubQuestion
from hmap.core.errors import Cancelled
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.research.synthesize")
PROMPT_VERSION = "1"
MAX_CLAIMS_PER_SUB = 4


class DraftClaim(BaseModel):
    sub_question: str = Field(description="sub-question id, e.g. S1.2")
    text: str = Field(description="one factual sentence, in your own words, supported by the cited evidence")
    evidence_ids: list[str] = Field(description="ids of the evidence that supports it, e.g. [\"E3\", \"E7\"]")


class SynthesisAnswer(BaseModel):
    claims: list[DraftClaim] = Field(default_factory=list)


SYSTEM = ("You write the findings of a research step. For each sub-question write 1-4 short factual claims. Every "
          "claim must be supported by the evidence quotes you cite (by id) — no outside knowledge, no claim without "
          "a citation. If the evidence does not answer a sub-question, write no claim for it. " +
          sanitize.UNTRUSTED_NOTE.replace("between <<<PAGE and PAGE>>>", "in the evidence quotes"))


def check_claims(claims: Sequence[Claim], evidence: Sequence[EvidenceDraft], sub_of: dict[str, str]) -> list[Issue]:
    """The citation critic: one issue per claim that is not properly cited (location ``/claims/<n>``)."""
    by_id = {e.id: e for e in evidence}
    issues: list[Issue] = []
    for n, c in enumerate(claims):
        loc = f"/claims/{n}"
        cited = [by_id[i] for i in c.evidence_ids if i in by_id]
        if not cited:
            issues.append(Issue(category="HALLUCINATION", severity="critical", location=loc,
                                description=f"claim {c.id} cites no existing evidence",
                                fix_hint="cite evidence ids that support it, or remove the claim"))
            continue
        sub = sub_of.get(c.id)
        if sub and any(e.sub_question != sub for e in cited):
            issues.append(Issue(category="CONSISTENCY", severity="minor", location=loc,
                                description=f"claim {c.id} cites evidence gathered for another sub-question"))
        if not quotes.words(c.text) & set().union(*(quotes.words(e.quote) for e in cited)):
            issues.append(Issue(category="HALLUCINATION", severity="major", location=loc,
                                description=f"claim {c.id} shares no words with the quotes it cites",
                                fix_hint="rewrite it from the cited quotes or remove it"))
    return issues


def rule_claims(evidence: Sequence[EvidenceDraft], subs: Sequence[SubQuestion]) -> tuple[list[Claim], dict[str, str]]:
    claims: list[Claim] = []
    sub_of: dict[str, str] = {}
    for s in subs:
        for e in [e for e in evidence if e.sub_question == s.id][:MAX_CLAIMS_PER_SUB]:
            cid = f"C{len(claims) + 1}"
            text = e.quote if len(e.quote) <= 300 else e.quote[:297].rsplit(" ", 1)[0] + "…"
            claims.append(Claim(id=cid, text=text, evidence_ids=[e.id]))
            sub_of[cid] = s.id
    return claims, sub_of


async def synthesize(subs: Sequence[SubQuestion], evidence: Sequence[EvidenceDraft],
                     llm: LLMClient | None) -> tuple[list[Claim], dict[str, str], list[str], str]:
    """(claims, claim id -> sub-question id, dropped claims with reasons, "model" | "rules")."""
    if not evidence:
        return [], {}, [], "rules"
    if llm is None:
        rule_made, rule_sub = rule_claims(evidence, subs)
        return rule_made, rule_sub, [], "rules"
    lines: list[str] = []
    for s in subs:
        mine = [e for e in evidence if e.sub_question == s.id]
        if not mine:
            continue
        lines.append(f"{s.id}: {s.text}")
        lines += [f"  {e.id} ({e.host or 'local'}): \"{e.quote}\"" for e in mine]
    try:
        resp = await llm.generate("reasoner", [{"role": "system", "content": SYSTEM},
                                               {"role": "user", "content": "\n".join(lines)}],
                                  schema=SynthesisAnswer, max_tokens=2000, temperature=0.2)
        drafts: list[DraftClaim] = resp.parsed.claims
    except Cancelled:
        raise
    except Exception as exc:
        log.info("research synthesis fell back to rules", error=type(exc).__name__)
        rule_made, rule_sub = rule_claims(evidence, subs)
        return rule_made, rule_sub, [], "rules"
    known = {e.id for e in evidence}
    subs_known = {s.id for s in subs}
    claims: list[Claim] = []
    sub_of: dict[str, str] = {}
    dropped: list[str] = []
    per_sub: dict[str, int] = {}
    for d in drafts:
        ids = [i.strip() for i in d.evidence_ids if i.strip() in known]
        text = " ".join(d.text.split())[:500]
        if not text:
            continue
        if not ids:
            dropped.append(f"{text[:100]} (no existing evidence cited)")
            continue
        sub = d.sub_question.strip() if d.sub_question.strip() in subs_known else \
            next(e.sub_question for e in evidence if e.id == ids[0])
        if per_sub.get(sub, 0) >= MAX_CLAIMS_PER_SUB:
            continue
        claim = Claim(id=f"C{len(claims) + 1}", text=text, evidence_ids=list(dict.fromkeys(ids)))
        problems = [i for i in check_claims([claim], evidence, {claim.id: sub}) if i.severity in ("major", "critical")]
        if problems:
            dropped.append(f"{text[:100]} ({problems[0].description.split(' ', 2)[-1]})")
            continue
        claims.append(claim)
        sub_of[claim.id] = sub
        per_sub[sub] = per_sub.get(sub, 0) + 1
    return claims, sub_of, dropped, "model"


def summary_markdown(questions: Sequence[str], subs: Sequence[SubQuestion], claims: Sequence[Claim],
                     sub_of: dict[str, str], evidence: Sequence[EvidenceDraft], stop_reason: str) -> str:
    """A short readable report: per question, its sub-questions and their claims with numbered citations."""
    numbers: dict[str, int] = {}
    sources: list[tuple[int, str, str]] = []
    by_id = {e.id: e for e in evidence}
    out: list[str] = []
    for qn, q in enumerate(questions):
        out.append(f"## {q}")
        for s in [s for s in subs if s.question == qn]:
            mine = [c for c in claims if sub_of.get(c.id) == s.id]
            out.append(f"\n**{s.text}** — {round(s.coverage * 100)} % covered")
            if not mine:
                out.append("- No sourced answer found.")
            for c in mine:
                refs = []
                for eid in c.evidence_ids:
                    e = by_id.get(eid)
                    if e is None:
                        continue
                    if e.url not in numbers:
                        numbers[e.url] = len(numbers) + 1
                        sources.append((numbers[e.url], e.title or e.url, e.url))
                    refs.append(f"[{numbers[e.url]}]")
                out.append(f"- {c.text} {''.join(dict.fromkeys(refs))}")
        out.append("")
    if sources:
        out.append("## Sources")
        out += [f"{n}. {t} — {u}" for n, t, u in sources]
    out.append(f"\n_Stopped: {stop_reason.replace('_', ' ')}._")
    return "\n".join(out).strip() + "\n"


# ---------------------------------------------------------------------------------------------- refinement (M4)


def refine_setup(report: ResearchReport, sub_of: dict[str, str], evidence: Sequence[EvidenceDraft]) -> object:
    """Member 4's ``RefineSetup`` for a research report (used when the task has ``refine=true``)."""
    from hmap.agents.refine import LLMRubricCritic, ProgrammaticCritic, RefineSetup, TargetedReviser
    from hmap.agents.refine.critics.rubric import Criterion, Rubric

    rubric = Rubric(name="research", version=PROMPT_VERSION,
                    subject="a research report: claims, each citing verbatim evidence quotes",
                    location_hint="the claim's JSON pointer, e.g. /claims/2",
                    criteria=(Criterion("R1", "Completeness: does every sub-question that has evidence get at least "
                                              "one claim that answers it?", 1.0, "OMISSION"),
                              Criterion("R2", "Support: does each claim say only what its cited quotes say?", 1.5,
                                        "HALLUCINATION")))

    def critic(output: ResearchReport, _input: object) -> list[Issue]:
        known = {c.id: sub_of.get(c.id, "") for c in output.claims}
        return check_claims(output.claims, evidence, known)

    def guard(patch: object, _doc: object, _input: object) -> str | None:
        path = getattr(patch, "path", "")
        if not (path.startswith("/claims") or path.startswith("/summary_markdown")):
            return "only claims and the summary may change (evidence and sources are facts)"
        return None

    return RefineSetup(artifact_type="research-report", load=ResearchReport.model_validate_json,
                       critics=[ProgrammaticCritic(critic, name="citations"),
                                LLMRubricCritic(rubric)],
                       reviser=TargetedReviser(load=ResearchReport.model_validate, guard=guard),
                       subject="research report")
