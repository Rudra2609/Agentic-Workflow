"""Rule pre-pass (spec item 2.5): keyword patterns find candidate requirements, constraints and deliverables with
exact spans. They are passed to the LLM as hints, raise the confidence of items both agree on, and are the whole
answer when no model is available (then every item gets a low confidence and the set says so)."""

import re
from dataclasses import dataclass

from hmap.agents.doc_intel.model import Block, SourceDocument

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")
MODAL_RE = re.compile(
    r"\b(must|shall|should|will need to|needs? to|has to|have to|(?:is|are) required to|required|is expected to|"
    r"are expected to|may|could|can optionally|optionally)\b", re.IGNORECASE)
MUST = {"must", "shall", "will need to", "need to", "needs to", "has to", "have to", "is required to",
        "are required to", "required", "is expected to", "are expected to"}
SHOULD = {"should"}
IMPERATIVE_RE = re.compile(
    r"^(write|implement|add|build|create|draw|design|develop|protect|measure|make|provide|include|support|allow|"
    r"ensure|test|document|show|display|store|save|handle|validate|deploy|compute|calculate|return|plot|"
    r"compare|explain|describe|prepare|present|record|log|identify|define|model)\b", re.IGNORECASE)
DELIVERABLE_RE = re.compile(r"\b(submit|hand in|hand-in|upload|send|deliver)\b|\.(zip|pdf|py|docx|ipynb)\b|"
                            r"\b(zip|pdf) file\b|\breport\b|\breadme\b|\bscreenshot\b|\bvideo\b", re.IGNORECASE)
CONSTRAINT_RE = re.compile(
    r"\b(do not use|don't use|not allowed|only|at most|no more than|maximum of|written in|use (?:python|java|c\+\+|"
    r"react|django|fastapi|tcp|the|a|an)\b|deadline|before \d|by \d|due\b|groups? of|budget|version \d|"
    r"standard library)", re.IGNORECASE)
TECH_RE = re.compile(r"\b(python|java|javascript|typescript|react|django|fastapi|flask|node|c\+\+|sql|pandas|"
                     r"matplotlib|plotly|pytest|tcp|http|rest|docker|git)\b", re.IGNORECASE)
SECTION_KIND = [
    (re.compile(r"constraint|rule|restriction|technical|limitation|assumption|policy", re.I), "C"),
    (re.compile(r"submi|deliverable|hand[- ]?in|what to (?:submit|hand)|handin|upload", re.I), "D"),
    (re.compile(r"requirement|task|scope|feature|function|what .* (?:do|has to)|specification", re.I), "R"),
]
SKIP_SECTION_RE = re.compile(r"background|introduction|overview|objective|about|setup|context", re.IGNORECASE)


@dataclass
class RuleHit:
    kind: str                # R | C | D
    text: str
    doc_index: int
    block_id: str
    priority: str = "must"
    ckind: str = "other"


def priority_of(text: str) -> str:
    m = MODAL_RE.search(text)
    if not m:
        return "must"
    word = m.group(1).lower()
    if word in MUST:
        return "must"
    if word in SHOULD:
        return "should"
    return "could"


def constraint_kind(text: str) -> str:
    low = text.lower()
    if TECH_RE.search(text) or "library" in low or "framework" in low:
        return "technology"
    if any(w in low for w in ("deadline", "before", "due", " by ", "group", "team", "portal", "change the code",
                              "command")):
        return "process"
    if any(w in low for w in ("budget", "server", "hardware", "hosting")):
        return "resource"
    if any(w in low for w in ("page", "minute", "words", "format", "file", "pdf", "longer than")):
        return "format"
    return "other"


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.split(text) if s.strip()]


def _section_kind(path: list[str]) -> str | None:
    for title in reversed(path):
        for pattern, kind in SECTION_KIND:
            if pattern.search(title):
                return kind
    return None


def classify_sentence(sentence: str, block: Block) -> str | None:
    section = _section_kind(block.section_path)
    has_modal = bool(MODAL_RE.search(sentence))
    imperative = bool(IMPERATIVE_RE.match(sentence))
    if DELIVERABLE_RE.search(sentence) and (section == "D" or re.match(r"(?i)^(submit|hand in|send|upload)\b",
                                                                        sentence)):
        return "D"
    if section == "C" or (CONSTRAINT_RE.search(sentence) and not has_modal and not imperative):
        return "C"
    if section == "D" and block.type == "list_item":
        return "D"
    if has_modal or (imperative and section in ("R", None)):
        if block.section_path and SKIP_SECTION_RE.search(block.section_path[-1]) and not has_modal:
            return None
        return "R"
    return None


def is_lead_in(sentence: str) -> bool:
    """"At minimum, your code needs to support:" introduces a list; it is context, not an item."""
    return sentence.rstrip().endswith(":")


def lead_in_kind(lead: str, block: Block) -> str:
    """Items under a lead-in are requirements unless the lead-in (or its section) says deliverables/constraints."""
    kind = classify_sentence(lead.rstrip(": ") + ".", block)
    return kind if kind in ("C", "D") else "R"


def rule_pass(docs: list[SourceDocument]) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for doc_index, doc in enumerate(docs):
        lead: tuple[str, str, str] | None = None  # (lead-in text, kind, priority) for the list that follows
        for block in doc.blocks:
            if block.type not in ("paragraph", "list_item"):
                lead = None
                continue
            if block.type == "list_item" and lead is not None:
                lead_text, lead_kind, lead_priority = lead
                item = block.text.strip().rstrip(".;")
                hits.append(RuleHit(lead_kind, f"{lead_text.rstrip(': ')}: {item}.", doc_index, block.id,
                                    priority=lead_priority,
                                    ckind=constraint_kind(item) if lead_kind == "C" else "other"))
                continue
            lead = None
            for sentence in sentences(block.text):
                if is_lead_in(sentence):
                    lead = (sentence, lead_in_kind(sentence, block), priority_of(sentence))
                    continue
                kind = classify_sentence(sentence, block)
                if kind is None:
                    continue
                hits.append(RuleHit(kind, sentence, doc_index, block.id, priority=priority_of(sentence),
                                    ckind=constraint_kind(sentence) if kind == "C" else "other"))
    return hits
