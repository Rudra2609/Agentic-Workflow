"""What "an agent" is (doc 01 §4 "Agent plug-in contract"). A member's agent subclasses ``BaseAgent`` and
implements ``handle``; everything else (registration, heartbeats, ack/progress/result messages, dedup,
cancellation, retries) is done by the runtime in ``hmap.core.runtime.worker``.

    class EchoAgent(BaseAgent):
        name = "echo"
        capabilities = ("echo",)

        async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
            ref = await ctx.put_json({"echo": task.objective}, artifact_type="echo")
            return ctx.result([ref], summary="echoed")
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from hmap.core.contracts import ArtifactRef, TaskAssign, TaskResult
from hmap.core.errors import Cancelled
from hmap.core.llm.base import LLMClient
from hmap.services.artifact.base import ArtifactStore
from hmap.services.context.base import ContextStore

M = TypeVar("M", bound=BaseModel)
ProgressFn = Callable[..., Awaitable[None]]  # (percent, summary, artifact_refs=None)


@dataclass
class AgentContext:
    """Everything a handler may use. Agents never touch the bus or the database directly."""

    task: TaskAssign
    agent_id: str
    llm: LLMClient
    artifacts: ArtifactStore
    context: ContextStore
    logger: Any
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    _progress: ProgressFn | None = None

    @property
    def project_id(self) -> str:
        return self.task.project_id or "default"

    async def progress(self, percent: int, summary: str, artifact_refs: list[ArtifactRef] | None = None) -> None:
        """Report progress (at-most-once telemetry, research §22). ``artifact_refs`` (Sprint 4) travel with the
        ``task.progress`` event, e.g. a refinement trace the UI can show while the task is still running."""
        if self._progress is not None:
            if artifact_refs:
                await self._progress(max(0, min(100, percent)), summary, artifact_refs)
            else:
                await self._progress(max(0, min(100, percent)), summary)

    def check_cancelled(self) -> None:
        """Call between steps; raises Cancelled so the runtime reports a cancelled execution."""
        if self.cancelled.is_set():
            raise Cancelled("execution cancelled")

    async def put_json(self, obj: BaseModel | dict[str, Any], *, artifact_type: str,
                       artifact_id: str | None = None) -> ArtifactRef:
        data = obj.model_dump_json(indent=2) if isinstance(obj, BaseModel) else json.dumps(obj, indent=2)
        return await self.artifacts.put(data.encode(), project_id=self.project_id, artifact_type=artifact_type,
                                        media_type="application/json", created_by=self.agent_id,
                                        artifact_id=artifact_id)

    async def get_json(self, ref: ArtifactRef, model: type[M]) -> M:
        return model.model_validate_json(await self.artifacts.get(ref, project_id=self.project_id))

    def result(self, artifact_refs: list[ArtifactRef], *, summary: str | None = None,
               outcome: str = "success", evidence: list[str] | None = None) -> TaskResult:
        return TaskResult(execution_id=self.task.execution_id, outcome=outcome,
                          artifact_refs=artifact_refs, summary=summary, evidence=evidence or [])


class BaseAgent:
    """Subclass, set ``name`` and ``capabilities``, implement ``handle``. One instance serves many tasks."""

    name: ClassVar[str] = ""
    capabilities: ClassVar[tuple[str, ...]] = ()
    max_slots: ClassVar[int] = 1          # concurrent executions (bounded prefetch)
    is_stub: ClassVar[bool] = False
    version: ClassVar[str] = "1.0"

    async def on_start(self) -> None:
        """Optional: warm caches/models before registering."""

    async def on_stop(self) -> None:
        """Optional: release resources."""

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        raise NotImplementedError
