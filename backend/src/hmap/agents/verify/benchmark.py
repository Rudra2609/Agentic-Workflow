"""The seeded-hallucination benchmark (``samples/verify/``, item 6.9) as Python objects, and one item verified.

Used by the tests and by ``backend/tests/verify/eval/run_eval.py``. Pages come from the item's ``page`` path; the
counter-sources of ``contradiction`` items become L4 passages (``origin="counter"``); L3 searches a local store of
every benchmark page + Member 5's offline corpus (so the synthetic counter pages can be *found* independently).
"""

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from hmap.agents.research.model import Page
from hmap.agents.verify import textual
from hmap.agents.verify.model import ClaimCheck, Passage, Quote
from hmap.agents.verify.pipeline import VerifyDeps, check_claim
from hmap.core.config import REPO_ROOT

BENCH_DIR = REPO_ROOT / "samples" / "verify"
BENCHMARK = BENCH_DIR / "benchmark.jsonl"
PAGES_DIR = BENCH_DIR / "pages"
SEARCH_CACHE = BENCH_DIR / "search_cache"
KINDS = ("clean", "fake_quote", "wrong_number", "unsupported_claim", "contradiction", "natural")


@dataclass
class Item:
    id: str
    kind: str
    claim: str
    evidence: list[Quote]
    counter: list[Quote]
    expected: str
    difficulty: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def load(path: Path = BENCHMARK) -> list[Item]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append(Item(id=d["id"], kind=d["kind"], claim=d["claim"],
                        evidence=[Quote.model_validate(e) for e in d["evidence"]],
                        counter=[Quote.model_validate(e) for e in d.get("counter_evidence") or []],
                        expected=d["expected"]["verdict"], difficulty=d.get("difficulty", ""), raw=d))
    return out


@cache
def page_file(rel: str) -> Page | None:
    path = BENCH_DIR / rel
    if not path.is_file():
        return None
    return Page.model_validate_json(path.read_text(encoding="utf-8"))


async def load_page(q: Quote) -> Page | None:
    return page_file(q.page) if q.page else None


def counter_passages(item: Item) -> list[Passage]:
    return [Passage(url=q.url, host=textual.host(q.url), text=q.quote, overlap=round(textual.overlap(item.claim,
                    q.quote), 3), origin="counter") for q in item.counter]


async def verify_item(item: Item, deps: VerifyDeps, *, use_counter: bool = True) -> ClaimCheck:
    evidence = {q.id: q for q in item.evidence}
    return await check_claim(item.id, item.claim, [q.id for q in item.evidence], evidence, deps,
                             counter=counter_passages(item) if use_counter else ())
