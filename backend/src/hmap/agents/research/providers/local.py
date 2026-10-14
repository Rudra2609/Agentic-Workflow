"""The ``local`` provider (Sprint 5 item 5.2 "LocalCorpus"): BM25 over the offline corpus, the local page cache and
the project's own uploaded documents. Works with no network at all."""

from hmap.agents.research.corpus import PageStore, tokens
from hmap.agents.research.model import Hit, Kind, Page


class LocalProvider:
    name = "local"
    kind: Kind = "local"
    network = False

    def __init__(self, store: PageStore, project_pages: list[Page] | None = None) -> None:
        self.store = store
        self.project_pages = project_pages or []

    async def search(self, query: str, k: int = 5) -> list[Hit]:
        ranked = [(p, s) for p, s in self.store.search(query, k)]
        q = set(tokens(query))
        for page in self.project_pages:                    # the project's own documents: simple word overlap
            overlap = len(q & set(tokens(page.title + " " + page.text[:20000])))
            if q and overlap / len(q) >= 0.5:
                ranked.append((page, float(overlap)))
        ranked.sort(key=lambda ps: -ps[1])
        return [Hit(provider=self.name, kind=p.kind, rank=n, query=query, url=p.url, title=p.title,
                    snippet=p.text[:300], published=p.published) for n, (p, _) in enumerate(ranked[:k])]
