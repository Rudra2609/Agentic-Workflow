"""Plug-in declaration and discovery (Sprint 1 §3.5). Every member package exposes ``hmap/agents/<name>/plugin.py``
with a module-level ``PLUGIN = Plugin(...)``. Discovery imports them; nobody edits a shared registry file.

    PLUGIN = Plugin(
        name="doc_intel",
        agents=[DocIntelAgent],
        router=router,                         # FastAPI APIRouter, mounted at /api/<name>
        manager_hooks=[on_document_uploaded],  # functions decorated with @hook(...)
        provides={"executor": None, "recovery": None, "llm_provider": None},
        priority=100,                          # stubs use 0: a real plug-in for a capability wins
    )
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from hmap.core.contracts import ArtifactRef, DomainEvent, TaskGraph

if TYPE_CHECKING:
    from hmap.core.runtime.base import BaseAgent
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

    async def emit(self, event: DomainEvent) -> None:
        """Publish a domain event through the outbox."""

    async def get_task(self, task_id: str) -> dict[str, Any]: ...


HookFn = Callable[[DomainEvent, ManagerHandle], Awaitable[None]]


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
    priority: int = 100
    description: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.provides) - set(STRATEGY_SLOTS)
        if unknown:
            raise ValueError(f"plugin {self.name}: unknown strategy slots {sorted(unknown)}")
