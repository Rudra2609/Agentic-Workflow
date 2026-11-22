"""Grounding checker (Sprint 9 item 9.6, plan D7): every technical claim of the generated documents, checked
against the facts of the repository. Rules first (``rules.py``, free and offline), then the model for behaviour
claims (``behaviour.py``). Result: an :class:`~hmap.agents.docgen.model.Accuracy` (claim table + percentages).

    acc = await check_documents({"readme": md, "api": md2}, facts, files, llm)   # llm=None: rules only
"""

import re

from hmap.agents.docgen.grounding import behaviour
from hmap.agents.docgen.grounding.rules import FENCE, Checker, sentences
from hmap.agents.docgen.model import Accuracy, Claim, Facts


def rule_claims(markdown: str, facts: Facts, doc: str = "") -> list[Claim]:
    return Checker(facts).check(markdown, doc)


def summarize(claims: list[Claim], removed: list[Claim] | None = None) -> Accuracy:
    acc = Accuracy(claims=claims, removed=list(removed or []))
    for c in claims:
        row = acc.by_doc.setdefault(c.doc or "-", {"grounded": 0, "ungrounded": 0, "unverified": 0, "unchecked": 0})
        row[c.verdict] += 1
    acc.grounded = sum(c.verdict == "grounded" for c in claims)
    acc.ungrounded = sum(c.verdict == "ungrounded" for c in claims)
    acc.unverified = sum(c.verdict == "unverified" for c in claims)
    acc.checked = acc.grounded + acc.ungrounded + sum(c.verdict == "ungrounded" for c in acc.removed)
    acc.grounded_pct = round(100.0 * acc.grounded / acc.checked, 2) if acc.checked else 100.0
    return acc


async def check_documents(docs: dict[str, str], facts: Facts, files: dict[str, str], llm: object = None, *,
                          behaviour_check: bool = True) -> tuple[Accuracy, dict[str, int | str | None]]:
    """-> (accuracy, stats ``{model_calls, tokens, behaviour}``)."""
    checker = Checker(facts)
    claims: list[Claim] = []
    calls = tokens = 0
    skipped: str | None = None
    for name, md in docs.items():
        if name == "summaries_json":
            continue
        found = checker.check(md, name)
        claims += found
        if behaviour_check and llm is not None:
            prose = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), md)
            ruled = {c.line for c in found}
            cand = behaviour.candidates(sentences(prose), ruled, name)
            got, c, t, why = await behaviour.check(llm, cand, files, name)  # type: ignore[arg-type]
            claims += got
            calls, tokens = calls + c, tokens + t
            skipped = skipped or why
    return summarize(_dedupe(claims)), {"model_calls": calls, "tokens": tokens, "behaviour": skipped}


def _dedupe(claims: list[Claim]) -> list[Claim]:
    seen: set[tuple[str, str, str, int]] = set()
    out = []
    for c in claims:
        key = (c.doc, c.kind, c.text, c.line)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def remove_sentences(markdown: str, bad: list[Claim]) -> tuple[str, list[Claim]]:
    """Final gate (plan D9): drop each ungrounded sentence (or table row / command line) from the document.
    Returns the cleaned document and the claims whose sentence was removed."""
    lines = markdown.split("\n")
    removed: list[Claim] = []
    for c in sorted(bad, key=lambda c: -c.line):
        i = c.line - 1
        if not (0 <= i < len(lines)):
            continue
        line = lines[i]
        target = c.sentence if c.kind != "COMMAND" or line.strip() != c.sentence else line.strip()
        if target and target in line:
            new = line.replace(target, "", 1)
            if not re.sub(r"[\s|*>\-`#.]", "", new):       # nothing left but markup: drop the line
                lines[i] = "\x00"
            else:
                lines[i] = re.sub(r"\s{2,}", " ", new).rstrip()
            removed.append(c)
        elif c.text and c.text in line:
            lines[i] = "\x00"
            removed.append(c)
    return "\n".join(x for x in lines if x != "\x00"), removed


__all__ = ["Checker", "check_documents", "remove_sentences", "rule_claims", "summarize"]
