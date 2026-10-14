"""Source scoring and selection (Sprint 5 item 5.6, plan D8). Explainable: every selected chunk keeps its
``relevance x authority x recency x novelty`` breakdown (shown in the Research tab, stored in ``Source``).

- relevance: the hybrid rank (RRF of dense + keyword), 0..1;
- authority: a small table of domain classes (standards, official docs, encyclopaedia, papers, universities high;
  Q&A sites, unknown blogs medium; known content farms low);
- recency: 1.0 unless the sub-question asks for current facts ("latest", a year, "2025", "current"), then newer
  pages score higher;
- novelty: 1 - the highest cosine similarity to a chunk already selected (or already used as evidence);
- duplicates (same ``content_sha256`` / same URL) are dropped, near-duplicates (shingle Jaccard >= 0.9) too.
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit

from hmap.agents.research.index import Retrieved, cosine
from hmap.agents.research.model import Scored

AUTHORITY: tuple[tuple[str, float], ...] = (
    # standards / official documentation
    (r"(^|\.)(rfc-editor\.org|ietf\.org|w3\.org|iso\.org|python\.org|docs\.python\.org|pytest\.org|"
     r"readthedocs\.io|developer\.mozilla\.org|oracle\.com|microsoft\.com|postgresql\.org|nodejs\.org)$", 1.0),
    (r"\.(gov|edu|ac\.[a-z]{2})$", 0.95),
    (r"(^|\.)(arxiv\.org|acm\.org|ieee\.org|springer\.com|nature\.com|usenix\.org)$", 0.95),
    (r"(^|\.)wikipedia\.org$", 0.9),
    (r"(^|\.)(github\.com|stackoverflow\.com|stackexchange\.com|realpython\.com)$", 0.75),
    (r"(^|\.)(medium\.com|dev\.to|hashnode\.dev|blogspot\.com|wordpress\.com)$", 0.55),
    (r"(^|\.)(geeksforgeeks\.org|w3schools\.com|tutorialspoint\.com|javatpoint\.com|programiz\.com)$", 0.5),
    (r"(^|\.)(pinterest\.[a-z.]+|quora\.com|answers\.com|ehow\.com|scribd\.com|coursehero\.com)$", 0.2),
)
DEFAULT_AUTHORITY = 0.6
LOCAL_AUTHORITY = 0.8          # the project's own uploaded documents
_RECENT = re.compile(r"\b(latest|current|currently|recent|newest|today|this year|20[2-9][0-9])\b", re.IGNORECASE)


def authority(url: str) -> float:
    if url.startswith("project://"):
        return LOCAL_AUTHORITY
    host = (urlsplit(url).hostname or "").lower()
    for pattern, value in AUTHORITY:
        if re.search(pattern, host):
            return value
    return DEFAULT_AUTHORITY


def recency(published: str | None, question: str, now: datetime | None = None) -> float:
    if not _RECENT.search(question):
        return 1.0
    if not published:
        return 0.7
    try:
        year = int(published[:4])
    except ValueError:
        return 0.7
    age = (now or datetime.now(UTC)).year - year
    return max(0.3, 1.0 - 0.15 * max(0, age))


def shingles(text: str, n: int = 5) -> set[str]:
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


SAME_PAGE = 0.5       # a second passage from a page already used for this sub-question counts less (diversity)


def select(candidates: Sequence[Retrieved], *, question: str, k: int, published: dict[str, str | None] | None = None,
           already: Sequence[list[float]] = (), seen_text: Sequence[str] = (),
           used_urls: Sequence[str] = ()) -> list[Scored]:
    """The top ``k`` chunks for one sub-question, greedily (novelty and page diversity recomputed after each pick:
    an answer needs two independent sources, so a second passage from the same page is worth less)."""
    published = published or {}
    urls = list(used_urls)
    chosen: list[Scored] = []
    vectors: list[list[float]] = [v for v in already if v]
    seen = [shingles(t) for t in seen_text]
    pool = list(candidates)
    while pool and len(chosen) < k:
        best: tuple[float, int, dict[str, float]] | None = None
        for n, r in enumerate(pool):
            nov = 1.0 - max((cosine(r.vector, v) for v in vectors), default=0.0) if r.vector else 1.0
            br = {"relevance": round(r.relevance, 4), "authority": authority(r.chunk.url),
                  "recency": round(recency(published.get(r.chunk.url), question), 4),
                  "novelty": round(max(0.0, min(1.0, nov)), 4)}
            score = br["relevance"] * br["authority"] * br["recency"] * (0.5 + 0.5 * br["novelty"])
            if r.chunk.url in urls:
                score *= SAME_PAGE
            if best is None or score > best[0]:
                best = (score, n, br)
        assert best is not None
        score, n, br = best
        r = pool.pop(n)
        sh = shingles(r.chunk.text)
        if any(jaccard(sh, s) >= 0.9 for s in seen):          # near-duplicate of something already chosen
            continue
        seen.append(sh)
        urls.append(r.chunk.url)
        if r.vector:
            vectors.append(r.vector)
        chosen.append(Scored(chunk=r.chunk, score=round(score, 4), breakdown=br))
    return chosen
