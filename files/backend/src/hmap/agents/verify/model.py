"""Working records of the verifier (Sprint 6) and the ``verification-trace`` artifact body. The contract handed on
(``VerificationReport`` / ``ClaimVerdict``) lives in ``hmap.core.contracts.domain``."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.domain import Verdict

REPORT_TYPE = "verification-report"
TRACE_TYPE = "verification-trace"
RESEARCH_REPORT_TYPE = "research-report"
LAYERS = ("l1", "l2", "l3", "l4")

Label = Literal["supports", "refutes", "not_enough"]
L1Reason = Literal["ok", "unknown_evidence", "page_missing", "hash_mismatch", "url_mismatch", "quote_not_found"]


def now() -> datetime:
    return datetime.now(UTC)


class Quote(BaseModel):
    """One piece of cited evidence as the verifier sees it (from a ``ResearchReport`` or a benchmark item)."""

    id: str
    url: str
    quote: str
    content_sha256: str
    page_artifact: ArtifactRef | None = None
    page: str | None = None              # benchmark: path of the saved page (samples/verify/pages/...)


class L1Result(BaseModel):
    evidence_id: str
    ok: bool
    reason: L1Reason
    detail: str = ""


class Judgement(BaseModel):
    """One entailment decision (L2 on the cited quotes, L4 on a passage from another source)."""

    label: Label
    rationale: str = ""
    by: Literal["model", "rules"] = "model"
    swapped_label: Label | None = None    # position-bias control: same question, passage first
    guard: str = ""                       # the rule that changed the model's label (e.g. a number missing)

    @property
    def unsure(self) -> bool:
        return self.swapped_label is not None and self.swapped_label != self.label


class Passage(BaseModel):
    """A sentence or two from another source (L3), or a counter-source handed in (benchmark)."""

    url: str
    host: str
    title: str = ""
    text: str
    overlap: float = 0.0                  # share of the claim's content words found in the passage
    origin: Literal["independent", "counter"] = "independent"
    query: str = ""
    published: str | None = None


class Comparison(BaseModel):
    """L4 on one passage: rule signals + (when asked) a judgement."""

    passage: Passage
    signals: list[str] = Field(default_factory=list)   # "number 20 vs 5", "negation", "year 2019 vs 2021"
    judgement: Judgement | None = None

    @property
    def conflict(self) -> bool:
        return self.judgement is not None and self.judgement.label == "refutes"

    @property
    def agrees(self) -> bool:
        return self.judgement is not None and self.judgement.label == "supports"


class AtomCheck(BaseModel):
    """Every layer's result for one atomic claim."""

    atom_id: str
    text: str
    check_worthy: bool = True
    l1: list[L1Result] = Field(default_factory=list)
    l2: Judgement | None = None
    l3_queries: list[str] = Field(default_factory=list)
    l3_passages: int = 0
    l4: list[Comparison] = Field(default_factory=list)
    independent_hosts: list[str] = Field(default_factory=list)
    row: str = ""
    verdict: Verdict = "NEEDS_MORE_RESEARCH"
    confidence: float = 0.0
    explanation: str = ""


class ClaimCheck(BaseModel):
    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    atoms: list[AtomCheck] = Field(default_factory=list)
    verdict: Verdict = "NEEDS_MORE_RESEARCH"
    confidence: float = 0.0
    explanation: str = ""
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)


class VerificationTrace(BaseModel):
    """Body of the ``verification-trace`` artifact (``vt-<task_id>``): what the Verify tab shows besides the report."""

    task_id: str
    project_id: str
    research_task_id: str | None = None
    research_report: ArtifactRef | None = None
    layers: list[str] = Field(default_factory=lambda: list(LAYERS))
    round: int = 0
    follow_up_of: ArtifactRef | None = None          # the earlier verification-report this one re-checks
    status: Literal["running", "done"] = "running"
    claims: list[ClaimCheck] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    model_calls: int = 0
    tokens: int = 0
    seconds: float = 0.0
    started_at: datetime = Field(default_factory=now)
    finished_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)
