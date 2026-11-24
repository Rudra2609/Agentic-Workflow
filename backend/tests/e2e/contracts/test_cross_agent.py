"""Item 10.18: the cross-agent contract suite (Member 10). Every producer -> consumer pair on the **real JSON** the
agents produced in the recorded golden run (``samples/review/contracts/``, exported by
``tests.review.eval.export_contracts``): the producer's artifact validates against its contract, and the consumer's
own parsing code accepts it and gets something out of it.

| Pair | Producer artifact | Consumer code |
|---|---|---|
| M2 -> M3 | RequirementSet | the planner's validation of a plan against it (``validate_plan``) |
| M3 -> Manager | TaskGraph | ``Manager.submit_graph`` (one task per plan step) |
| M5 -> M6 | ResearchReport | every verdict of the verification report refers to one of its claims |
| M6 -> M10 | VerificationReport | the review's verification evidence |
| M7 -> M8 | CodeChangeSet | the workspace tarball it points at holds the changed files |
| M8 -> M7 | TestReport | ``code.revise``'s ``from_test_report`` |
| M8 / M9 -> M10 | TestReport, DocBundle | the review's evidence |
| M10 -> M7 | ReviewReport | ``code.revise``'s ``from_review_report`` |
"""

import json
from pathlib import Path
from typing import Any

import pytest

from hmap.agents.coding.revise import from_review_report, from_test_report
from hmap.agents.coding.workspace import files_from_tar
from hmap.agents.planning.validate import errors, validate_plan
from hmap.core.contracts import (
    CodeChangeSet,
    DocBundle,
    RequirementSet,
    ResearchReport,
    ReviewReport,
    TaskGraph,
    TestReport,
    VerificationReport,
)
from hmap.core.contracts.capabilities import CAPABILITY_OUTPUTS

DIR = Path(__file__).resolve().parents[4] / "samples" / "review" / "contracts"
pytestmark = pytest.mark.skipif(not (DIR / "SOURCE.json").exists(),
                                reason="no recorded contracts yet (scripts/demo_final.sh --record, then "
                                       "python -m tests.review.eval.export_contracts)")


def load(name: str) -> Any:
    return json.loads((DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_every_pipeline_output_was_recorded_and_validates() -> None:
    models = {"requirement-set": RequirementSet, "task-graph": TaskGraph, "research-report": ResearchReport,
              "verification-report": VerificationReport, "code-change-set": CodeChangeSet,
              "test-report": TestReport, "doc-bundle": DocBundle, "review-report": ReviewReport}
    wanted = {"requirement-set", "task-graph"} | {t for t, _ in CAPABILITY_OUTPUTS.values()}
    assert wanted <= set(models)
    for name in sorted(wanted):
        models[name].model_validate(load(name))


def test_m2_to_m3_and_m3_to_manager() -> None:
    rs = RequirementSet.model_validate(load("requirement-set"))
    graph = TaskGraph.model_validate(load("task-graph"))
    assert not errors(validate_plan(graph, rs)), "the recorded plan does not validate against its requirements"
    assert graph.coverage_matrix, "the plan has a coverage matrix"


async def test_m3_to_manager_submit_graph() -> None:
    from hmap.core.bus.memory import InMemoryBus
    from hmap.core.bus.outbox import InMemoryOutboxStore
    from hmap.manager.manager import Manager
    from hmap.manager.store import InMemoryTaskStore
    from hmap.services.artifact.memory import InMemoryArtifactStore
    from hmap.services.context.memory import InMemoryContextStore
    from hmap.services.registry.memory import InMemoryRegistry

    graph = TaskGraph.model_validate(load("task-graph"))
    outbox = InMemoryOutboxStore()
    m = Manager(bus=InMemoryBus(), store=InMemoryTaskStore(outbox), outbox=outbox, registry=InMemoryRegistry(),
                artifacts=InMemoryArtifactStore(), contexts=InMemoryContextStore())
    pid = await m.create_project("contract", project_id=graph.project_id)
    await m.submit_graph(pid, graph, require_approval=False)
    tasks = [t for t in await m.list_tasks(pid) if t.get("plan_task_id")]
    assert len(tasks) == len(graph.tasks)


def test_m5_to_m6() -> None:
    research = ResearchReport.model_validate(load("research-report"))
    verdicts = VerificationReport.model_validate(load("verification-report"))
    ids = {c.id for c in research.claims}
    assert all(v.claim_id.split(".")[0] in ids or v.claim_id in ids for v in verdicts.claim_verdicts)


def test_m7_to_m8() -> None:
    cs = CodeChangeSet.model_validate(load("code-change-set"))
    files = files_from_tar((DIR / "workspace.tar.gz").read_bytes())
    assert cs.files_changed and all(f in files for f in cs.files_changed if not f.endswith("/"))


def test_m8_to_m7_and_m10_to_m7() -> None:
    changes, _ = from_test_report(TestReport.model_validate(load("test-report")))
    assert isinstance(changes, list)
    report = ReviewReport.model_validate(load("review-report"))
    asked = from_review_report(report, set())
    assert len(asked) == min(10, sum(len(p.required_changes) for p in report.revision_requests) + len(report.failures))


def test_m8_m9_m6_to_m10() -> None:
    from hmap.agents.review.checks import docs, tests, verification
    from hmap.agents.review.model import Evidence, Item, TestEv, VerificationEv

    rep = TestReport.model_validate(load("test-report"))
    item = Item(id="R1", text="x", evidence=Evidence(tests=[TestEv(name="t", status="passed" if rep.passed else
                                                                   "failed", covers=["R1"])]))
    assert tests.check(item) is not None
    bundle = DocBundle.model_validate(load("doc-bundle"))
    item = Item(id="R1", text="x", evidence=Evidence(doc_ungrounded=bundle.accuracy_report.ungrounded_claims))
    assert (docs.check(item) is None) == (not bundle.accuracy_report.ungrounded_claims)
    vr = VerificationReport.model_validate(load("verification-report"))
    if vr.claim_verdicts:
        item = Item(id="R1", text="x", evidence=Evidence(verification=[VerificationEv(claim=v.claim_id, verdict={
            "VERIFIED": "supported"}.get(v.verdict, "unsupported")) for v in vr.claim_verdicts]))
        assert verification.check(item) is not None
