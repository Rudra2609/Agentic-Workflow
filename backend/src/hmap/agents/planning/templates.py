"""Phase templates (spec item 3.1). Every plan gets the same spine, so its structure never depends on the model:

    research -> verify -> design -> [implement per part] -> [test per part] -> document -> review (single sink)

The model (or the rule planner) only fills in the implement / test / document steps of each part. Two project
kinds exist: ``software`` (something to build and run) and ``document`` (a report, essay or study to write).
"""

import re
from dataclasses import dataclass

from hmap.core.contracts.capabilities import (
    CAPABILITY_OUTPUTS,
    CODE_IMPLEMENT,
    DOCS_GENERATE,
    DOCUMENT_EXTRACT,
    PLAN_GENERATE,
    RESEARCH_RUN,
    REVIEW_FINAL,
    TEST_RUN,
    VERIFY_CLAIMS,
)

# What a plan may assign (D2): the pipeline capabilities minus the two that make the plan itself. Stub agents
# register all of them, so every one always has an agent.
PLAN_CAPABILITIES: tuple[str, ...] = tuple(c for c in CAPABILITY_OUTPUTS if c not in (DOCUMENT_EXTRACT, PLAN_GENERATE))

KINDS = ("software", "document")

# words that point at software work vs. writing work (scored over requirements, constraints and deliverables)
_SOFTWARE = re.compile(
    r"\b(code|program|programs|server|client|implement\w*|function|class|api|database|schema|sql|app|application|"
    r"script|python|java|javascript|c\+\+|socket|tcp|http|unit test|pytest|compile\w*|algorithm|module|library|"
    r"git|repository|interface|cli|command|endpoint|frontend|backend|data structure)\b", re.I)
_DOCUMENT = re.compile(
    r"\b(essay|report|literature|review of|survey|reflect\w*|discuss\w*|argue|analy[sz]e|summar\w*|"
    r"citation\w*|references|bibliography|words|pages|chapter|case study|presentation|slides)\b", re.I)

# default capability of the steps the template asks each part for
PHASE_CAPABILITY: dict[str, dict[str, str]] = {
    "software": {"research": RESEARCH_RUN, "design": CODE_IMPLEMENT, "implement": CODE_IMPLEMENT,
                 "test": TEST_RUN, "document": DOCS_GENERATE, "review": REVIEW_FINAL},
    "document": {"research": RESEARCH_RUN, "design": DOCS_GENERATE, "implement": DOCS_GENERATE,
                 "test": VERIFY_CLAIMS, "document": DOCS_GENERATE, "review": REVIEW_FINAL},
}

# capabilities that make sense in each phase (unknown / misplaced ones are mapped back to the phase default)
PHASE_ALLOWED: dict[str, frozenset[str]] = {
    "research": frozenset({RESEARCH_RUN, VERIFY_CLAIMS}),
    "design": frozenset({CODE_IMPLEMENT, DOCS_GENERATE}),
    "implement": frozenset({CODE_IMPLEMENT, DOCS_GENERATE}),
    "test": frozenset({TEST_RUN, VERIFY_CLAIMS}),
    "document": frozenset({DOCS_GENERATE}),
    "review": frozenset({REVIEW_FINAL}),
}

# effort heuristics in hours (D10 / roadmap): spine steps, and per requirement for parts
EFFORT = {"research": 2.0, "verify": 1.0, "design": 2.0, "review": 1.0, "document": 2.0,
          "implement_per_requirement": 1.5, "test_base": 1.0, "test_per_requirement": 0.5}
MIN_EFFORT, MAX_EFFORT = 0.5, 16.0


@dataclass(frozen=True)
class SpineStep:
    id: str
    phase: str
    capability: str
    title: str
    description: str
    acceptance: tuple[str, ...]
    effort: float


SPINE: dict[str, tuple[SpineStep, ...]] = {
    "software": (
        SpineStep("research", "research", RESEARCH_RUN, "Research the approach",
                  "Find out what the team needs to know before designing: the techniques, libraries and pitfalls "
                  "the requirements involve.",
                  ("every research question has an answer with sources", "the answers name the options considered"),
                  EFFORT["research"]),
        SpineStep("verify", "research", VERIFY_CLAIMS, "Check the research findings",
                  "Verify the research report's claims against its sources before the design relies on them.",
                  ("every claim the design uses is supported by a source", "unsupported claims are marked"),
                  EFFORT["verify"]),
        SpineStep("design", "design", CODE_IMPLEMENT, "Design the solution",
                  "Decide the structure: modules, interfaces and data formats for every part, and set up the "
                  "project skeleton.",
                  ("each part has a module and an interface", "the skeleton runs", "the design follows the "
                   "constraints"), EFFORT["design"]),
        SpineStep("review", "review", REVIEW_FINAL, "Final review",
                  "Check the finished work against every requirement, constraint, deliverable and the marking "
                  "scheme before it is handed in.",
                  ("every must requirement is met", "every deliverable is present"), EFFORT["review"]),
    ),
    "document": (
        SpineStep("research", "research", RESEARCH_RUN, "Research the topic",
                  "Collect sources and facts the document needs.",
                  ("every research question has an answer with sources",), EFFORT["research"]),
        SpineStep("verify", "research", VERIFY_CLAIMS, "Check the research findings",
                  "Verify the collected claims against their sources.",
                  ("every claim the document uses is supported by a source",), EFFORT["verify"]),
        SpineStep("design", "design", DOCS_GENERATE, "Outline the document",
                  "Plan the structure: sections, the argument and which source supports which part.",
                  ("every requirement has a section in the outline",), EFFORT["design"]),
        SpineStep("review", "review", REVIEW_FINAL, "Final review",
                  "Check the finished document against every requirement, constraint and the marking scheme.",
                  ("every must requirement is met", "every deliverable is present"), EFFORT["review"]),
    ),
}

SPINE_IDS = frozenset({"research", "verify", "design", "review"})

# requirements no agent can do: a person has to (they are flagged, not planned)
HUMAN_ONLY = re.compile(
    r"\b(demonstrat\w* (it |your \w+ )?(to|in front of)|in person|"
    r"attend (the |a |your |every )?(class|lab|lecture|session|meeting|tutorial|viva)\w*|viva|oral exam|sign (the|a)|"
    r"meet (with|your)|present\w* (it |your \w+ )?(to|in) (the )?(class|ta|instructor|lab)|"
    r"present\w* (a )?(part of )?(the |a |your )?(demo|presentation|poster)|record\w* (a |the )?(demo )?video|"
    r"(upload|submit|hand)\w*\b[^.]{0,40}\b(to|on|via|through) (the )?(course )?"
    r"(portal|moodle|lms|google classroom|classroom|blackboard|canvas)|"
    r"hand\w* (it )?in (on|at)|physical\w*|printed copy)\b", re.I)

# deliverables that are documents (a docs step makes them); others (source, ZIP, program) come from the code steps
DOC_DELIVERABLE = re.compile(r"\b(readme|report|documentation|manual|guide|slides|presentation|diagram|design|"
                             r"essay|write-?up|reflection|summary|pdf|notes|poster)\b", re.I)
CODE_DELIVERABLE = re.compile(r"\b(source|code|zip|program|repository|repo|script|executable|binary|jar|"
                              r"notebook|project files?)\b", re.I)


def detect_kind(texts: list[str]) -> str:
    """``software`` unless the writing words clearly win (ties go to software: most course work is code)."""
    joined = "\n".join(texts)
    software = len(_SOFTWARE.findall(joined))
    document = len(_DOCUMENT.findall(joined))
    return "document" if document > software * 1.5 and document >= 2 else "software"


def clamp_effort(hours: float | None, default: float) -> float:
    if hours is None or hours != hours:  # None or NaN
        return default
    return round(min(MAX_EFFORT, max(MIN_EFFORT, float(hours))), 1)
