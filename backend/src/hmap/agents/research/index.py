"""Chunk + embed + hybrid retrieval (Sprint 5 item 5.5, plan D7). Reusable (Member 7 may index other text).

    index = HybridIndex(embed=ctx.llm.embed, backend=MemoryBackend())     # or PgBackend(db) on Postgres
    await index.add(project_id, page)                                     # sentence-aligned ~800-char chunks
    hits = await index.search(project_id, "how does asyncio handle many sockets", k=6)

Ranking = reciprocal rank fusion (RRF, k=60) of a **dense** ranking (cosine of ``nomic-embed-text`` vectors) and a
**keyword** ranking (BM25 in memory; ``ts_rank_cd`` over a ``tsvector`` in Postgres). Everything is namespaced by
project; ``delete_project`` removes a project's rows (called on ``project.deleted``).

Postgres (migration ``005_sprint_5_research``): table ``research_chunks`` with an untyped ``vector`` column (the
dimension follows the embedding model; tests use 8-dim fake vectors) and exact cosine search per project — a
project holds hundreds to a few thousand chunks, where an exact scan is fast and an HNSW index would not pay off.
"""

import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from hmap.agents.research.corpus import tokens
from hmap.agents.research.model import Chunk, Page, sha256_text
from hmap.core.errors import Cancelled
from hmap.core.tracing import get_logger

log = get_logger("hmap.research.index")

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]
CHUNK_CHARS = 800
MAX_CHUNKS_PER_PAGE = 40      # ~32 000 characters: the start of a long page; keeps local embedding time bounded
OVERLAP_CHARS = 120
EMBED_BATCH = 32
RRF_K = 60
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n{2,}")


def split_sentences(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        if m.start() > start:
            spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    out: list[tuple[int, int]] = []
    for s, e in spans:                     # very long "sentences" (lists, code) are cut at the chunk size
        while e - s > CHUNK_CHARS:
            cut = text.rfind(" ", s, s + CHUNK_CHARS)
            cut = cut if cut > s + CHUNK_CHARS // 2 else s + CHUNK_CHARS
            out.append((s, cut))
            s = cut
        if text[s:e].strip():
            out.append((s, e))
    return out


def chunk_page(page: Page, *, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[Chunk]:
    """Sentence-aligned chunks of about ``size`` characters; the next chunk repeats the last sentences up to
    ``overlap`` characters so a fact split across a boundary is still found whole."""
    sents = split_sentences(page.text)
    chunks: list[Chunk] = []
    i = 0
    base = sha256_text(page.url)[:12]
    while i < len(sents):
        j = i
        while j < len(sents) and (sents[j][1] - sents[i][0] <= size or j == i):
            j += 1
        start, end = sents[i][0], sents[j - 1][1]
        chunks.append(Chunk(id=f"{base}-{len(chunks)}", url=page.url, title=page.title, kind=page.kind,
                            text=page.text[start:end], start=start, end=end))
        if j >= len(sents):
            break
        back = j
        while back - 1 > i and sents[j - 1][1] - sents[back - 1][0] <= overlap:
            back -= 1
        i = back if back > i else j
    return chunks


@dataclass
class Retrieved:
    chunk: Chunk
    relevance: float                   # 0..1 (RRF normalised)
    dense_rank: int | None = None
    keyword_rank: int | None = None
    vector: list[float] | None = None


class Backend(Protocol):
    async def has(self, project_id: str, url: str, sha: str) -> bool: ...
    async def add(self, project_id: str, sha: str, chunks: Sequence[Chunk], vectors: Sequence[list[float]]) -> None: ...
    async def dense(self, project_id: str, vector: list[float], k: int,
                    urls: set[str] | None) -> list[tuple[Chunk, list[float]]]: ...
    async def keyword(self, project_id: str, query: str, k: int, urls: set[str] | None) -> list[Chunk]: ...
    async def vectors(self, project_id: str, chunk_ids: Sequence[str]) -> dict[str, list[float]]: ...
    async def delete_project(self, project_id: str) -> int: ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class _Project:
    chunks: list[Chunk] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)
    pages: set[tuple[str, str]] = field(default_factory=set)
    bm25: Any = None


class MemoryBackend:
    def __init__(self) -> None:
        self.projects: dict[str, _Project] = {}

    async def has(self, project_id: str, url: str, sha: str) -> bool:
        return (url, sha) in self.projects.get(project_id, _Project()).pages

    async def add(self, project_id: str, sha: str, chunks: Sequence[Chunk], vectors: Sequence[list[float]]) -> None:
        p = self.projects.setdefault(project_id, _Project())
        if chunks:
            p.pages.add((chunks[0].url, sha))
        p.chunks.extend(chunks)
        p.vectors.extend(vectors)
        p.bm25 = None

    async def dense(self, project_id: str, vector: list[float], k: int,
                    urls: set[str] | None) -> list[tuple[Chunk, list[float]]]:
        p = self.projects.get(project_id)
        if p is None:
            return []
        scored = [(cosine(vector, v), n) for n, (c, v) in enumerate(zip(p.chunks, p.vectors, strict=True))
                  if v and (urls is None or c.url in urls)]
        scored.sort(key=lambda sn: (-sn[0], sn[1]))
        return [(p.chunks[n], p.vectors[n]) for _, n in scored[:k]]

    async def keyword(self, project_id: str, query: str, k: int, urls: set[str] | None) -> list[Chunk]:
        from rank_bm25 import BM25Plus

        p = self.projects.get(project_id)
        q = tokens(query)
        if p is None or not p.chunks or not q:
            return []
        if p.bm25 is None:
            p.bm25 = BM25Plus([tokens(c.title) + tokens(c.text) for c in p.chunks])
        scores = p.bm25.get_scores(q)
        order = sorted((n for n in range(len(p.chunks)) if scores[n] > 0 and (urls is None or p.chunks[n].url in urls)),
                       key=lambda n: (-scores[n], n))
        return [p.chunks[n] for n in order[:k]]

    async def vectors(self, project_id: str, chunk_ids: Sequence[str]) -> dict[str, list[float]]:
        p = self.projects.get(project_id)
        if p is None:
            return {}
        wanted = set(chunk_ids)
        return {c.id: v for c, v in zip(p.chunks, p.vectors, strict=True) if c.id in wanted and v}

    async def delete_project(self, project_id: str) -> int:
        p = self.projects.pop(project_id, None)
        return len(p.chunks) if p else 0


def _vec_literal(v: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def _parse_vec(raw: Any) -> list[float]:
    if isinstance(raw, list | tuple):
        return [float(x) for x in raw]
    return [float(x) for x in str(raw).strip("[]").split(",") if x.strip()]


_COLS = "chunk_id, url, title, kind, start_char, end_char, text"


def _chunk(row: dict[str, Any]) -> Chunk:
    return Chunk(id=row["chunk_id"], url=row["url"], title=row["title"], kind=row["kind"], text=row["text"],
                 start=row["start_char"], end=row["end_char"])


class PgBackend:
    """``research_chunks`` in Postgres (pgvector). ``db`` is the platform's :class:`hmap.db.Database`."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def has(self, project_id: str, url: str, sha: str) -> bool:
        rows = await self.db.fetch("SELECT 1 FROM research_chunks WHERE project_id = %s AND url = %s AND "
                                   "content_sha256 = %s LIMIT 1", (project_id, url, sha))
        return bool(rows)

    async def add(self, project_id: str, sha: str, chunks: Sequence[Chunk], vectors: Sequence[list[float]]) -> None:
        async with self.db.transaction() as conn:
            for c, v in zip(chunks, vectors, strict=True):
                await conn.execute(
                    "INSERT INTO research_chunks (project_id, chunk_id, url, title, kind, content_sha256, start_char, "
                    "end_char, text, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector) "
                    "ON CONFLICT (project_id, chunk_id) DO NOTHING",
                    (project_id, c.id, c.url, c.title, c.kind, sha, c.start, c.end, c.text,
                     _vec_literal(v) if v else None))

    async def dense(self, project_id: str, vector: list[float], k: int,
                    urls: set[str] | None) -> list[tuple[Chunk, list[float]]]:
        params: list[Any] = [project_id, len(vector)]
        where = "project_id = %s AND embedding IS NOT NULL AND vector_dims(embedding) = %s"
        if urls is not None:
            where += " AND url = ANY(%s)"
            params.append(sorted(urls))
        rows = await self.db.fetch(
            f"SELECT {_COLS}, embedding::text AS vec FROM research_chunks WHERE {where} "
            f"ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s", (*params, _vec_literal(vector), k))
        return [(_chunk(r), _parse_vec(r["vec"])) for r in rows]

    async def keyword(self, project_id: str, query: str, k: int, urls: set[str] | None) -> list[Chunk]:
        terms = [t for t in tokens(query) if t.isalnum()][:20]
        if not terms:
            return []
        params: list[Any] = [" | ".join(terms), project_id]
        where = "project_id = %s AND tsv @@ q"
        if urls is not None:
            where += " AND url = ANY(%s)"
            params.append(sorted(urls))
        rows = await self.db.fetch(
            f"SELECT {_COLS} FROM research_chunks, to_tsquery('english', %s) q WHERE {where} "
            f"ORDER BY ts_rank_cd(tsv, q) DESC, chunk_id LIMIT %s", (*params, k))
        return [_chunk(r) for r in rows]

    async def vectors(self, project_id: str, chunk_ids: Sequence[str]) -> dict[str, list[float]]:
        if not chunk_ids:
            return {}
        rows = await self.db.fetch("SELECT chunk_id, embedding::text AS vec FROM research_chunks WHERE project_id = %s"
                                   " AND chunk_id = ANY(%s) AND embedding IS NOT NULL", (project_id, list(chunk_ids)))
        return {r["chunk_id"]: _parse_vec(r["vec"]) for r in rows}

    async def delete_project(self, project_id: str) -> int:
        rows = await self.db.fetch("DELETE FROM research_chunks WHERE project_id = %s RETURNING 1", (project_id,))
        return len(rows)


@dataclass
class HybridIndex:
    """``keyword_only`` turns on by itself when the embedding model fails (no Ollama, a missing recording): the
    keyword ranking keeps working and ``embed_error`` says why (shown in the trace)."""

    embed: EmbedFn
    backend: Backend
    embedded_texts: int = 0
    keyword_only: bool = False
    embed_error: str | None = None
    ranking: str = "hybrid"               # hybrid | dense | keyword (the retrieval ablation)

    async def add(self, project_id: str, page: Page) -> int:
        """Index ``page`` for ``project_id`` (no-op when this exact text is already indexed). Returns new chunks."""
        if await self.backend.has(project_id, page.url, page.content_sha256):
            return 0
        chunks = chunk_page(page)[:MAX_CHUNKS_PER_PAGE]
        vectors: list[list[float]] = []
        if not self.keyword_only:
            try:
                for i in range(0, len(chunks), EMBED_BATCH):
                    batch = [f"{c.title}\n{c.text}" if c.title else c.text for c in chunks[i:i + EMBED_BATCH]]
                    vectors += await self.embed(batch)
                    self.embedded_texts += len(batch)
            except Cancelled:
                raise
            except Exception as exc:  # no embedding model (or no recording): keyword search still works
                self._degrade(exc)
        if self.keyword_only:
            vectors = [[] for _ in chunks]
        await self.backend.add(project_id, page.content_sha256, chunks, vectors)
        return len(chunks)

    def _degrade(self, exc: BaseException) -> None:
        if not self.keyword_only:
            log.info("research index: embeddings unavailable, keyword search only", error=type(exc).__name__)
        self.keyword_only = True
        self.embed_error = type(exc).__name__

    async def search(self, project_id: str, query: str, k: int = 6, urls: set[str] | None = None,
                     pool: int = 20) -> list[Retrieved]:
        dense: list[tuple[Chunk, list[float]]] = []
        if not self.keyword_only and self.ranking != "keyword":
            try:
                [qvec] = await self.embed([query])
                self.embedded_texts += 1
                dense = await self.backend.dense(project_id, qvec, pool, urls)
            except Cancelled:
                raise
            except Exception as exc:
                self._degrade(exc)
        keyword = await self.backend.keyword(project_id, query, pool, urls) if self.ranking != "dense" else []
        fused: dict[str, Retrieved] = {}
        for rank, (c, v) in enumerate(dense):
            r = fused.setdefault(c.id, Retrieved(chunk=c, relevance=0.0, vector=v))
            r.dense_rank, r.relevance = rank, r.relevance + 1 / (RRF_K + rank + 1)
        for rank, c in enumerate(keyword):
            r = fused.setdefault(c.id, Retrieved(chunk=c, relevance=0.0))
            r.keyword_rank, r.relevance = rank, r.relevance + 1 / (RRF_K + rank + 1)
        missing = [cid for cid, r in fused.items() if r.vector is None]
        if missing:
            found = await self.backend.vectors(project_id, missing)
            for cid in missing:
                fused[cid].vector = found.get(cid)
        best = 2 / (RRF_K + 1)
        out = sorted(fused.values(), key=lambda r: (-r.relevance, r.chunk.id))[:k]
        for r in out:
            r.relevance = round(r.relevance / best, 4)
        return out

    async def delete_project(self, project_id: str) -> int:
        return await self.backend.delete_project(project_id)


def backend_for(context_store: Any) -> Backend:
    """Postgres when the platform runs on Postgres (the agent shares the context store's database and schema), else
    memory (shared per process, so one research step's pages are reused by the next)."""
    db = getattr(context_store, "db", None)
    try:
        from hmap.db.database import Database
    except Exception:  # pragma: no cover
        Database = None  # type: ignore[assignment,misc]
    if Database is not None and isinstance(db, Database):
        return PgBackend(db)
    return _SHARED_MEMORY


_SHARED_MEMORY = MemoryBackend()
