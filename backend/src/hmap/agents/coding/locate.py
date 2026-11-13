"""Locator (Sprint 7 item 7.3, plan D9): which files does a task need to change?

Hybrid ranking fused with weighted reciprocal-rank fusion (RRF, k=60; BM25 weight 1.0, embeddings 0.35):

1. **BM25** over identifiers (snake/camel split), docstrings, symbols and the file name (ported from
   ``samples/coding/locate.py``: top-1 7/7 on the benchmark's modify / bug-fix tasks);
2. **embeddings** (``embed`` role) of each file's outline vs the task, cached by content hash; skipped silently when
   no embedding model answers (fake / replay miss / Ollama down);
3. an **LLM rerank** (``fast`` role) of the top 6, only for repositories with more than 8 files.

Tests are ranked too (a failing test names the code under test), but code files win ties.
"""

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from hmap.agents.coding.repomap import RepoMap
from hmap.core.errors import Cancelled, HmapError
from hmap.core.llm.base import LLMClient, Message
from hmap.core.tracing import get_logger

log = get_logger("hmap.coding.locate")

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "be", "for", "on", "with", "when", "must",
        "should", "self", "def", "return", "import", "from", "none", "str", "int", "list", "dict", "true", "false",
        "if", "not", "as", "by", "at", "this", "that", "are", "was", "while", "one", "every", "bug", "report",
        "py", "file", "files", "class", "function", "test", "tests"}
RRF_K = 60
W_LEXICAL, W_DENSE = 1.0, 0.35
RERANK_MIN_FILES = 8
RERANK_TOP = 6
_EMBED_CACHE: dict[str, list[float]] = {}


def tokens(text: str) -> list[str]:
    words = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text):
        for part in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", word):
            part = part.lower()
            if len(part) > 1 and part not in STOP:
                words.append(part)
    return words


def bm25(files: dict[str, str], query: str, k1: float = 1.2, b: float = 0.75) -> list[tuple[str, float]]:
    docs = {path: Counter(tokens(text) + tokens(path.rsplit("/", 1)[-1].removesuffix(".py")) * 3)
            for path, text in files.items()}
    n = len(docs)
    avg = sum(sum(c.values()) for c in docs.values()) / max(n, 1)
    df = Counter(t for c in docs.values() for t in c)
    scores = {}
    q = set(tokens(query))
    for path, counts in docs.items():
        length = sum(counts.values()) or 1
        score = 0.0
        for t in q:
            if t in counts:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * counts[t] * (k1 + 1) / (counts[t] + k1 * (1 - b + b * length / max(avg, 1)))
        scores[path] = score
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _cos(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


class RerankAnswer(BaseModel):
    files: list[str] = Field(default_factory=list, description="file paths, most relevant first (only from the list)")


@dataclass
class Located:
    ranked: list[tuple[str, float]] = field(default_factory=list)   # fused, best first
    methods: list[str] = field(default_factory=list)                 # bm25 / embed / rerank
    tokens_used: int = 0

    def top(self, k: int = 3) -> list[str]:
        return [p for p, s in self.ranked[:k] if s > 0]


async def locate(rmap: RepoMap, files: dict[str, str], query: str, llm: LLMClient | None = None, *,
                 use_embeddings: bool = True, use_rerank: bool = True) -> Located:
    code = {p: t for p, t in files.items() if p.endswith(".py")}
    if not code or not query.strip():
        return Located()
    docs = {p: f"{t}\n{rmap.search_text(p) if p in rmap.entries else ''}" for p, t in code.items()}
    lexical = bm25(docs, query)
    rankings = [[p for p, _ in lexical]]
    methods = ["bm25"]
    out = Located(methods=methods)
    if llm is not None and use_embeddings:
        try:
            outline = {p: (rmap.search_text(p) if p in rmap.entries else p)[:2000] for p in code}
            keys = {p: hashlib.sha256(outline[p].encode()).hexdigest() for p in code}
            missing = [p for p in code if keys[p] not in _EMBED_CACHE]
            if missing:
                vectors = await llm.embed([outline[p] for p in missing])
                for p, v in zip(missing, vectors, strict=True):
                    _EMBED_CACHE[keys[p]] = v
            qv = (await llm.embed([query[:2000]]))[0]
            dense = sorted(code, key=lambda p: (-_cos(qv, _EMBED_CACHE[keys[p]]), p))
            rankings.append(dense)
            methods.append("embed")
        except Cancelled:
            raise
        except (HmapError, ValueError, KeyError) as exc:
            log.info("locator: no embeddings, BM25 only", error=type(exc).__name__)
    if len(rankings) == 1:     # BM25 only: its scores (0 = no evidence at all)
        out.ranked = sorted(((p, round(s, 5)) for p, s in lexical), key=lambda x: (-x[1], _is_test(x[0]), x[0]))
    else:                      # weighted RRF: lexical evidence first, embeddings break ties / fill no-evidence cases
        fused: dict[str, float] = dict.fromkeys(code, 0.0)
        lex = dict(lexical)
        for rank, p in enumerate(rankings[0]):
            if lex[p] > 0:
                fused[p] += W_LEXICAL / (RRF_K + rank + 1)
        for rank, p in enumerate(rankings[1]):
            fused[p] += W_DENSE / (RRF_K + rank + 1)
        out.ranked = sorted(((p, round(s, 5)) for p, s in fused.items()), key=lambda x: (-x[1], _is_test(x[0]), x[0]))
    if llm is not None and use_rerank and len(code) > RERANK_MIN_FILES:
        top = [p for p, _ in out.ranked[:RERANK_TOP]]
        listing = "\n".join(f"- {p}: {(rmap.search_text(p) if p in rmap.entries else p)[:300]}" for p in top)
        msgs = [Message(role="system", content="You pick the source files a coding task must change. Answer with "
                                               "file paths from the list only, most relevant first."),
                Message(role="user", content=f"Task:\n{query[:1500]}\n\nCandidate files:\n{listing}")]
        try:
            resp = await llm.generate("fast", msgs, schema=RerankAnswer, max_tokens=200, temperature=0.0, seed=7)
            chosen = [p for p in resp.parsed.files if p in top]
            if chosen:
                order = chosen + [p for p in top if p not in chosen]
                scores = dict(out.ranked)
                best = max(scores.values()) or 1.0
                out.ranked = [(p, round(best * (1 + (len(order) - i) / 100), 5)) for i, p in enumerate(order)] + \
                    out.ranked[RERANK_TOP:]
                methods.append("rerank")
            out.tokens_used += resp.usage.input_tokens + resp.usage.output_tokens
        except Cancelled:
            raise
        except HmapError as exc:
            log.info("locator: rerank skipped", error=type(exc).__name__)
    return out


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}"
