"""Internal data of the research agent (Sprint 5). The contracts handed on (``ResearchReport`` & co.) live in
``hmap.core.contracts.domain``; these are the working records and the ``research-trace`` artifact body."""

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from hmap.core.contracts import ArtifactRef

Kind = Literal["web", "wiki", "arxiv", "local"]

BRIEF_TYPE = "research-brief"
REPORT_TYPE = "research-report"
TRACE_TYPE = "research-trace"
PAGE_TYPE = "research-page"


def now() -> datetime:
    return datetime.now(UTC)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def url_key(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


class Hit(BaseModel):
    """One search result. ``content`` is set when the provider already returns the text (arXiv abstracts, the local
    corpus): then nothing is fetched."""

    provider: str
    kind: Kind = "web"
    url: str
    title: str = ""
    snippet: str = ""
    rank: int = 0
    query: str = ""
    published: str | None = None
    content: str | None = None


class Page(BaseModel):
    """A fetched and cleaned page. ``text`` is exactly what quotes are checked against; ``content_sha256`` is its
    hash (Member 6 re-checks both)."""

    url: str
    final_url: str | None = None
    title: str = ""
    kind: Kind = "web"
    provider: str = ""
    text: str
    content_sha256: str
    retrieved_at: datetime = Field(default_factory=now)
    published: str | None = None
    media_type: str = "text/html"
    from_cache: bool = False
    injection_lines_removed: int = 0
    license: str | None = None

    @property
    def host(self) -> str:
        from urllib.parse import urlsplit

        return (urlsplit(self.final_url or self.url).hostname or "").lower()


class Chunk(BaseModel):
    id: str
    url: str
    title: str = ""
    kind: Kind = "web"
    text: str
    start: int
    end: int


class Scored(BaseModel):
    chunk: Chunk
    score: float
    breakdown: dict[str, float] = Field(default_factory=dict)


class EvidenceDraft(BaseModel):
    """Evidence after the quote check (the contract ``Evidence`` is made from it at the end)."""

    id: str
    sub_question: str
    url: str
    title: str = ""
    quote: str
    char_start: int
    char_end: int
    content_sha256: str
    retrieved_at: datetime
    why: str = ""
    host: str = ""


class RoundTrace(BaseModel):
    index: int
    queries: list[dict[str, Any]] = Field(default_factory=list)      # {sub_question, provider, query, hits}
    hits: int = 0
    fetched: int = 0
    fetch_failures: dict[str, int] = Field(default_factory=dict)      # reason -> count
    selected: list[dict[str, Any]] = Field(default_factory=list)      # {sub_question, url, chunk, score, breakdown}
    triaged: int = 0
    relevant: int = 0
    quotes_proposed: int = 0
    quotes_dropped: int = 0
    new_evidence: int = 0
    novelty: float = 0.0
    coverage: dict[str, float] = Field(default_factory=dict)
    tokens: int = 0
    seconds: float = 0.0


class ResearchTrace(BaseModel):
    """Body of the ``research-trace`` artifact: everything the Research tab shows besides the report."""

    task_id: str
    project_id: str
    mode: str
    providers: list[str] = Field(default_factory=list)
    status: Literal["running", "stopped"] = "running"
    rounds: list[RoundTrace] = Field(default_factory=list)
    stop_reason: str | None = None
    planner: str = ""                     # "model" | "rules"
    synthesis: str = ""                   # "model" | "rules"
    claims_dropped: list[str] = Field(default_factory=list)
    tokens: int = 0
    model_calls: int = 0
    seconds: float = 0.0
    pages: list[ArtifactRef] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=now)
    finished_at: datetime | None = None
    follow_up_of: ArtifactRef | None = None
    notes: list[str] = Field(default_factory=list)
