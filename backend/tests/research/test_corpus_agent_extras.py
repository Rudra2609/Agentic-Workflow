"""The committed offline corpus (5.14: licences, hashes), the agent's idempotency, the refinement switch (5.9) and
the failure-injection hooks the chaos tests and the mid-eval demo rely on."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from hmap.agents.research.agent import ResearchAgent
from hmap.agents.research.corpus import CORPUS_DIR, PageStore
from hmap.agents.research.model import Page
from hmap.core.contracts import TaskAssign
from hmap.core.errors import HmapError
from hmap.core.ids import new_execution_id, new_task_id
from hmap.core.llm import FakeLLM
from hmap.core.runtime.base import AgentContext
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from tests.research.conftest import ASYNCIO_URL, FakeProvider, cached
from tests.research.eval.run_eval import LICENSES, gold, licence_for

LICENSES_MD = CORPUS_DIR.parent / "LICENSES.md"


def test_every_committed_page_has_a_permissive_licence_and_its_hash() -> None:
    files = sorted(CORPUS_DIR.glob("*.json"))
    assert len(files) >= 40
    for f in files:
        page = Page.model_validate_json(f.read_text(encoding="utf-8"))
        assert page.license and page.license == licence_for(page.url), page.url
        assert page.content_sha256 == hashlib.sha256(page.text.encode()).hexdigest()
    assert LICENSES_MD.is_file() and all(lic is None or lic.split(" (")[0] in LICENSES_MD.read_text()
                                         for lic in LICENSES.values())


def test_gold_set_shape() -> None:
    rows = gold()
    assert len(rows) == 10 and all(len(r["facts"]) >= 3 for r in rows)


def _task(**inputs: Any) -> TaskAssign:
    return TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability="research.run",
                      objective="research", acceptance_criteria=[], context_refs=[], project_id="P-R",
                      inputs={"research_questions": ["Threads or an asyncio event loop for many sockets?"], **inputs})


def _ctx(task: TaskAssign, store: InMemoryArtifactStore) -> AgentContext:
    return AgentContext(task=task, agent_id="research-1", llm=FakeLLM(default=None), artifacts=store,
                        context=InMemoryContextStore(), logger=None)


@pytest.fixture
def agent(store: PageStore, tmp_path: Path) -> ResearchAgent:
    from hmap.agents.research.fetch import Fetcher

    provider = cached(FakeProvider(hits={"threads": [ASYNCIO_URL], "asyncio": [ASYNCIO_URL]}), tmp_path)
    return ResearchAgent(providers=[provider], fetcher=Fetcher(store=store), store=store)


async def test_a_redelivered_task_returns_the_stored_result(agent: ResearchAgent) -> None:
    store = InMemoryArtifactStore()
    task = _task()
    first = await agent.handle(task, _ctx(task, store))
    n = len(await store.list("P-R"))
    again = await agent.handle(task, _ctx(task, store))
    assert [r.artifact_id for r in again.artifact_refs] == [r.artifact_id for r in first.artifact_refs]
    assert len(await store.list("P-R")) == n and "redelivered" in (again.summary or "")


async def test_refine_switch_adds_a_refinement_trace(agent: ResearchAgent) -> None:
    store = InMemoryArtifactStore()
    task = _task().model_copy(update={"refine": True})
    result = await agent.handle(task, _ctx(task, store))
    types = [r.artifact_type for r in result.artifact_refs]
    assert types[0] == "research-report" and "refinement-trace" in types


async def test_failure_injection_is_honoured(agent: ResearchAgent) -> None:
    store = InMemoryArtifactStore()
    task = _task(stub_fail="TOOL_TRANSIENT", stub_fail_times=1)
    with pytest.raises(HmapError):
        await agent.handle(task, _ctx(task, store))
    assert (await agent.handle(task, _ctx(task, store))).outcome == "success"     # second attempt goes through
    report = json.loads(await store.get(next(r for r in await store.list("P-R") if r.artifact_type ==
                                             "research-report"), project_id="P-R"))
    assert report["task_id"] == task.task_id
