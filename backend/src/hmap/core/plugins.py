"""Plug-in declaration and discovery (Sprint 1 §3.5). Every member package exposes ``hmap/agents/<name>/plugin.py``
with a module-level ``PLUGIN = Plugin(...)``. Discovery imports them; nobody edits a shared registry file.

    PLUGIN = Plugin(
        name="doc_intel",
        agents=[DocIntelAgent],
        router=router,                         # FastAPI APIRouter, mounted at /api/<name>
        manager_hooks=[on_document_uploaded],  # functions decorated with @hook(...)
        provides={"executor": None, "recovery": None, "llm_provider": None},
        refiners={"document.extract": adapter},  # Sprint 4: check-and-improve hook (see ``RefineAdapter``)
        priority=100,                          # stubs use 0: a real plug-in for a capability wins
    )
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from hmap.core.contracts import ArtifactRef, DomainEvent, TaskGraph

if TYPE_CHECKING:
    from hmap.core.contracts import TaskAssign, TaskResult
    from hmap.core.runtime.base import AgentContext, BaseAgent
    from hmap.services.artifact.base import ArtifactStore
    from hmap.services.context.base import ContextStore

STRATEGY_SLOTS = ("executor", "recovery", "llm_provider")


class ProjectStopped(ValueError):
    """Raised by ``create_task`` / ``submit_graph`` when a human stopped the project. Hooks may let it propagate:
    the dispatcher treats it as "nothing to do" (logged at info level, not as a hook failure)."""


class ManagerHandle(Protocol):
    """What a Manager hook may do. Implemented by hmap.manager (Member 1). ``create_task`` and ``submit_graph``
    raise :class:`ProjectStopped` for a stopped project."""

    artifacts: "ArtifactStore"
    contexts: "ContextStore"

    async def create_task(self, project_id: str, capability: str, objective: str, *,
                          acceptance_criteria: list[str] | None = None, inputs: dict[str, Any] | None = None,
                          artifact_refs: list[ArtifactRef] | None = None, depends_on: list[str] | None = None,
                          parent_task_id: str | None = None) -> str:
        """Create a READY task (or CREATED until ``depends_on`` complete); returns task_id."""

    async def submit_graph(self, project_id: str, graph: TaskGraph, *, require_approval: bool = True) -> None:
        """Hand a TaskGraph to the executor; with approval required the project waits in AWAITING_APPROVAL."""

    async def replace_graph(self, project_id: str, graph: TaskGraph, *,
                            require_approval: bool = True) -> dict[str, str]:
        """Replan (Sprint 3): swap the current plan for a newer version, keeping completed / running plan tasks
        whose ids are still in ``graph``; returns plan task id -> task id."""

    async def emit(self, event: DomainEvent) -> None:
        """Publish a domain event through the outbox."""

    async def get_task(self, task_id: str) -> dict[str, Any]: ...


HookFn = Callable[[DomainEvent, ManagerHandle], Awaitable[None]]


class RefineAdapter(Protocol):
    """Refinement hook for an existing capability (Sprint 4, plan D1). When a task arrives with ``refine=true`` (a
    project setting the Manager copies into ``TaskAssign.refine``), the agent runtime calls the adapter registered
    for the task's capability with the agent's successful result, *before* the result is reported. The adapter
    returns the result to report: the same one, or a new one with improved artifacts. The agent's own code is not
    involved, so an owner's plug-in never has to change for its output to be checked and improved.

    ``ctx`` is the task's context, but its ``llm`` is bound to the adapter's plug-in (its own replay cache). An
    exception in the adapter is logged and the original result is reported unchanged (refinement never breaks the
    base behaviour); :class:`~hmap.core.errors.Cancelled` is propagated."""

    async def __call__(self, task: "TaskAssign", result: "TaskResult", ctx: "AgentContext") -> "TaskResult": ...


@dataclass(frozen=True)
class Hook:
    event_type: str          # e.g. "document.uploaded" or "task.completed"
    fn: HookFn
    capability: str | None = None  # for task.* events: only when the task's capability matches


def hook(event_type: str, *, capability: str | None = None) -> Callable[[HookFn], Hook]:
    def wrap(fn: HookFn) -> Hook:
        return Hook(event_type=event_type, fn=fn, capability=capability)
    return wrap


@dataclass
class Plugin:
    name: str
    agents: list[type["BaseAgent"]] = field(default_factory=list)
    router: Any | None = None
    manager_hooks: list[Hook] = field(default_factory=list)
    provides: dict[str, Any] = field(default_factory=dict)
    refiners: dict[str, RefineAdapter] = field(default_factory=dict)  # capability -> adapter (Sprint 4)
    priority: int = 100
    description: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.provides) - set(STRATEGY_SLOTS)
        if unknown:
            raise ValueError(f"plugin {self.name}: unknown strategy slots {sorted(unknown)}")
