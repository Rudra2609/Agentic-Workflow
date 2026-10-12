"""One valid, realistic example of every contract.

Used by contract tests (every example must validate against its exported JSON Schema) and by the Sprint-1 stub
agents, which return these canned outputs so the pipeline runs end-to-end before the real agents exist.
"""

from datetime import UTC, datetime
from typing import Any

from hmap.core.contracts import domain as d
from hmap.core.contracts import messages as m
from hmap.core.contracts.capabilities import CapabilityDescriptor
from hmap.core.contracts.common import ArtifactRef, ContextRef, Contract
from hmap.core.contracts.events import DomainEvent, EventType
from hmap.core.contracts.states import AgentState

T0 = datetime(2026, 10, 1, 10, 15, tzinfo=UTC)
PROJECT = "P-01J9DEMO0000000000000000AA"
TASK = "T-01J9DEMO0000000000000000AB"
EXECUTION = "E-01J9DEMO0000000000000000AC"


def artifact(artifact_id: str = "ART-91", artifact_type: str = "json", *, version: int = 1,
             media_type: str = "application/json", created_by: str = "stub-agent") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id, artifact_type=artifact_type, version=version,
        uri=f"file://artifacts/{PROJECT}/{artifact_id}/v{version}/{'0' * 64}", sha256="0" * 64,
        media_type=media_type, size_bytes=1234, created_by=created_by, created_at=T0, access_scope=PROJECT,
    )


SRC = d.SourceRef(doc_id="ART-DOC-1", page=1,
                  quote="The server must accept connections from at least 10 concurrent clients.")

MESSAGE_EXAMPLES: dict[str, Contract] = {
    "task.assign": m.TaskAssign(
        task_id=TASK, execution_id=EXECUTION, capability="research.run",
        objective="Research TCP concurrency models in Python",
        acceptance_criteria=["every claim cites evidence", "covers threads and asyncio"],
        context_refs=[ContextRef(context_id="CTX-42", version=3)], project_id=PROJECT,
        dependencies=["T-01J9DEMO0000000000000000A9"], inputs={"research_questions": ["threads vs asyncio?"]},
    ),
    "task.ack": m.TaskAck(execution_id=EXECUTION, decision="accepted", available_slots=0),
    "task.started": m.TaskStarted(execution_id=EXECUTION),
    "task.progress": m.TaskProgress(execution_id=EXECUTION, percent=40, summary="fetched 4/10 sources"),
    "task.result": m.TaskResult(execution_id=EXECUTION, outcome="success",
                                artifact_refs=[artifact("ART-92", "research-report")], summary="report ready"),
    "feedback": m.Feedback(target_execution_id=EXECUTION, decision="revise", findings=["claim C3 uncited"],
                           severity="warning"),
    "revision.request": m.RevisionRequest(new_execution_id="E-01J9DEMO0000000000000000AD",
                                          target_execution_id=EXECUTION, required_changes=["cite claim C3"]),
    "context.request": m.ContextRequest(execution_id=EXECUTION, question="Which Python version is allowed?"),
    "error": m.ErrorPayload(execution_id=EXECUTION, error_code="MODEL_TRANSIENT", message="ollama timed out",
                            retryable=True),
    "retry.request": m.RetryRequest(execution_id=EXECUTION, reason="model timeout", requested_delay_seconds=5),
    "task.cancel": m.TaskCancel(task_id=TASK, reason="human changed the plan"),
    "task.completed": m.TaskCompleted(execution_id=EXECUTION, final_status="completed", result_ref="ART-92@1"),
    "agent.heartbeat": m.AgentHeartbeat(agent_id="research-1a2b3c4d", state=AgentState.BUSY, observed_at=T0,
                                        available_slots=0, current_execution_ids=[EXECUTION]),
    "agent.register": m.AgentRegister(
        agent_id="research-1a2b3c4d", endpoint="hmap.cap.research.run",
        capabilities=[CapabilityDescriptor(name="research.run", inputs=["ResearchBrief"],
                                           constraints={"max_concurrency": 1})],
        protocol_versions=["1.0"], plugin="research",
    ),
    "agent.deregister": m.AgentDeregister(agent_id="research-1a2b3c4d", reason="shutdown"),
}

REQUIREMENT_SET = d.RequirementSet(
    project_id=PROJECT,
    source_docs=[artifact("ART-DOC-1", "document", media_type="application/pdf", created_by="api")],
    requirements=[
        d.Requirement(id="R1", text="Accept at least 10 concurrent clients", source_ref=SRC, confidence=0.95),
        d.Requirement(id="R2", text="Broadcast every message to all other clients", priority="must",
                      source_ref=d.SourceRef(doc_id="ART-DOC-1", page=1), confidence=0.9),
    ],
    constraints=[d.Constraint(id="C1", text="Python 3 standard library only", kind="technology")],
    deliverables=[d.Deliverable(id="D1", name="server.py and client.py", format="zip")],
    evaluation_criteria=[d.EvaluationCriterion(id="E1", criterion="Correct broadcast", max_marks=60),
                         d.EvaluationCriterion(id="E2", criterion="Report", max_marks=40)],
    open_questions=["Is IPv6 support required?"],
    total_marks=100,
)

TASK_GRAPH = d.TaskGraph(
    project_id=PROJECT,
    tasks=[
        d.PlanTask(id="T1", title="Research concurrency models", agent_capability="research.run",
                   requirement_ids=["R1"], phase="research", research_questions=["threads vs asyncio for 10 clients?"]),
        d.PlanTask(id="T2", title="Implement server and client", agent_capability="code.implement",
                   requirement_ids=["R1", "R2"], depends_on=["T1"], acceptance_criteria=["10 clients connect"]),
        d.PlanTask(id="T3", title="Run multi-client tests", agent_capability="test.run", requirement_ids=["R1", "R2"],
                   depends_on=["T2"], phase="test"),
        d.PlanTask(id="T4", title="Write README and report", agent_capability="docs.generate", depends_on=["T2"],
                   phase="document"),
        d.PlanTask(id="T5", title="Final review", agent_capability="review.final", depends_on=["T3", "T4"],
                   phase="review"),
    ],
    roadmap=d.Roadmap(phases=[d.Phase(id="PH1", name="Build", task_ids=["T1", "T2", "T3"]),
                              d.Phase(id="PH2", name="Deliver", task_ids=["T4", "T5"])]),
    coverage_matrix={"R1": ["T1", "T2", "T3"], "R2": ["T2", "T3"]},
)

RESEARCH_REPORT = d.ResearchReport(
    task_id=TASK, questions=["threads vs asyncio?"],
    claims=[d.Claim(id="C1", text="asyncio runs coroutines on a single-threaded event loop", evidence_ids=["EV1"])],
    evidence=[d.Evidence(id="EV1", url="https://docs.python.org/3/library/asyncio.html",
                         quote="asyncio is a library to write concurrent code using the async/await syntax.",
                         content_sha256="1" * 64, retrieved_at=T0, sub_question="threads vs asyncio?")],
    sources=[d.Source(url="https://docs.python.org/3/library/asyncio.html", title="asyncio", score=0.9)],
    coverage={"threads vs asyncio?": 1.0}, stop_reason="all_covered",
)

DOMAIN_EXAMPLES: dict[str, Contract] = {
    "RequirementSet": REQUIREMENT_SET,
    "TaskGraph": TASK_GRAPH,
    "RefinementSpec": d.RefinementSpec(producer="doc_intel.extract", critics=["schema", "quote_match"],
                                       reviser="targeted", stop_policy={"max_iters": 3, "threshold": 0.9}),
    "RefinementTrace": d.RefinementTrace(
        spec=d.RefinementSpec(producer="doc_intel.extract", critics=["schema"], reviser="targeted"),
        iterations=[d.RefinementIteration(index=0, critique=d.Critique(score=0.7, issues=[
            d.Issue(category="OMISSION", severity="major", description="private messages requirement missing")]),
            score=0.7), d.RefinementIteration(index=1, critique=d.Critique(score=0.95), score=0.95)],
        best_iteration=1, stop_reason="threshold"),
    "ResearchBrief": d.ResearchBrief(task_id=TASK, questions=["threads vs asyncio for a 10-client chat server?"]),
    "ResearchReport": RESEARCH_REPORT,
    "VerificationReport": d.VerificationReport(task_id=TASK, claim_verdicts=[
        d.ClaimVerdict(claim_id="C1", verdict="VERIFIED", confidence=0.9, supporting=["EV1"])]),
    "CodeChangeSet": d.CodeChangeSet(task_id=TASK,
                                     workspace_ref=artifact("ART-WS", "workspace", media_type="application/x-tar"),
                                     files_changed=["server.py", "client.py"],
                                     commands_run=[d.CommandRun(cmd="python -m py_compile server.py", exit_code=0)]),
    "TestReport": d.TestReport(task_id=TASK, stages={"static": d.StageResult(status="passed"),
                                                     "unit": d.StageResult(status="failed")},
                               failures=[d.TestFailure(category="ASSERTION", file="test_chat.py", line=42,
                                                       message="client 3 never received the broadcast",
                                                       hint="broadcast loop skips the last client")],
                               passed=False, coverage=71.5),
    "DocBundle": d.DocBundle(task_id=TASK, readme_ref=artifact("ART-README", "markdown", media_type="text/markdown"),
                             accuracy_report=d.AccuracyReport(grounded_pct=96.0, ungrounded_claims=["uses Redis"])),
    "ReviewReport": d.ReviewReport(project_id=PROJECT,
                                   requirement_results=[d.RequirementResult(req_id="R1", verdict="PASS",
                                                                            evidence=["TestReport unit passed"])],
                                   rubric_scores=[d.RubricScore(criterion_id="E1", score=55, max_marks=60)],
                                   overall=0.9, recommendation="PASS"),
    "ModelSpec": d.ModelSpec(id="qwen3.5:9b", family="qwen3.5", params_b=9, quant="Q4_K_M", ctx=8192, mem_gb=5.8,
                             roles_ok=["reasoner", "judge", "coder", "fast"]),
    "RouteDecision": d.RouteDecision(role="reasoner", model="qwen3.5:9b", backend="ollama",
                                     reason="HMAP_ROLE_MAP default"),
    "BenchmarkResult": d.BenchmarkResult(model="qwen3.5:9b", role="reasoner", task="extraction", quality_score=0.95,
                                         tok_s=14.2),
}

EVENT_EXAMPLE = DomainEvent(event_type=EventType.TASK_COMPLETED, aggregate_id=TASK, aggregate_version=7,
                            occurred_at=T0, project_id=PROJECT, data={"execution_id": EXECUTION})


def all_examples() -> dict[str, Any]:
    return {**{f"message:{k}": v for k, v in MESSAGE_EXAMPLES.items()},
            **{f"domain:{k}": v for k, v in DOMAIN_EXAMPLES.items()},
            "event:DomainEvent": EVENT_EXAMPLE}
