"""Small fakes for runtime tests (the real in-memory bus/inbox/LLM gateway are built in parallel)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hmap.core.bus.base import CommandHandler, DeadLetter, EventHandler
from hmap.core.contracts import DomainEvent, Envelope, TaskAssign, make_envelope
from hmap.core.ids import new_execution_id, new_task_id
from hmap.core.llm.base import LLMResponse
from hmap.core.tracing import new_traceparent


@dataclass
class FakeDelivery:
    body: Envelope | DomainEvent
    attempt: int = 1
    redelivered: bool = False
    settled: str | None = None  # "ack" | "nack" | "reject"
    reason: str | None = None

    async def ack(self) -> None:
        self._settle("ack")

    async def nack(self, *, requeue: bool = True, delay_s: float | None = None) -> None:
        self._settle("nack")

    async def reject(self, reason: str) -> None:
        self.reason = reason
        self._settle("reject")

    def _settle(self, how: str) -> None:
        assert self.settled is None, f"delivery settled twice ({self.settled}, then {how})"
        self.settled = how


@dataclass
class FakeSubscription:
    bus: "FakeBus"
    key: tuple[str, str]
    cancelled: bool = False

    async def cancel(self) -> None:
        self.cancelled = True
        self.bus.handlers.pop(self.key, None)


@dataclass
class FakeBus:
    """Records replies; ``deliver`` calls the registered command handler directly (awaited)."""

    replies: list[Envelope] = field(default_factory=list)
    handlers: dict[tuple[str, str], tuple[Any, int]] = field(default_factory=dict)
    fail_replies: Callable[[Envelope], bool] | None = None
    reply_event: asyncio.Event = field(default_factory=asyncio.Event)

    async def start(self) -> None: ...
    async def close(self) -> None: ...

    async def send_command(self, capability: str, envelope: Envelope) -> None:
        raise NotImplementedError

    async def publish_event(self, event: DomainEvent) -> None:
        await self.emit(event)

    async def send_reply(self, envelope: Envelope) -> None:
        if self.fail_replies is not None and self.fail_replies(envelope):
            raise ConnectionError("broker down")
        # cross a "broker": serialise + re-parse like the real adapters
        self.replies.append(Envelope.model_validate_json(envelope.model_dump_json()))
        self.reply_event.set()

    async def consume_commands(self, capability: str, handler: CommandHandler, *,
                               prefetch: int = 1) -> FakeSubscription:
        key = ("cmd", capability)
        self.handlers[key] = (handler, prefetch)
        return FakeSubscription(self, key)

    async def consume_replies(self, handler: CommandHandler, *, prefetch: int = 16) -> FakeSubscription:
        raise NotImplementedError

    async def subscribe_events(self, pattern: str, handler: EventHandler, *,
                               queue: str | None = None) -> FakeSubscription:
        key = ("evt", pattern)
        self.handlers[key] = (handler, 16)
        return FakeSubscription(self, key)

    async def dead_letters(self) -> list[DeadLetter]:
        return []

    async def queue_depths(self) -> dict[str, int]:
        return {}

    # -- test helpers
    async def deliver(self, capability: str, envelope: Envelope, **kw: Any) -> FakeDelivery:
        handler, _ = self.handlers[("cmd", capability)]
        delivery = FakeDelivery(Envelope.model_validate_json(envelope.model_dump_json()), **kw)
        await handler(delivery)
        return delivery

    async def emit(self, event: DomainEvent) -> FakeDelivery | None:
        entry = self.handlers.get(("evt", event.event_type))
        if entry is None:
            return None
        delivery = FakeDelivery(event)
        await entry[0](delivery)
        return delivery

    def types(self, *, execution_id: str | None = None) -> list[str]:
        return [e.message_type for e in self.replies if execution_id is None or e.execution_id == execution_id]

    def of_type(self, message_type: str) -> list[Envelope]:
        return [e for e in self.replies if e.message_type == message_type]

    async def wait_for(self, predicate: Callable[["FakeBus"], bool], timeout: float = 2.0) -> None:
        async with asyncio.timeout(timeout):
            while not predicate(self):
                self.reply_event.clear()
                await self.reply_event.wait()


class DictInbox:
    def __init__(self) -> None:
        self.keys: set[tuple[str, str]] = set()

    async def seen(self, consumer_id: str, message_id: str) -> bool:
        return (consumer_id, message_id) in self.keys

    async def record(self, consumer_id: str, message_id: str) -> bool:
        if (consumer_id, message_id) in self.keys:
            return False
        self.keys.add((consumer_id, message_id))
        return True


class FakeLLM:
    async def generate(self, role: Any, messages: Any, **kw: Any) -> LLMResponse:
        return LLMResponse(text="ok")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    async def classify(self, state: str, questions: list[Any]) -> list[Any]:
        return []


def assign_envelope(capability: str = "echo", *, objective: str = "say hi", project_id: str = "P-TEST",
                    inputs: dict[str, Any] | None = None, task_id: str | None = None,
                    execution_id: str | None = None, **task_kw: Any) -> Envelope:
    task = TaskAssign(task_id=task_id or new_task_id(), execution_id=execution_id or new_execution_id(),
                      capability=capability, objective=objective, acceptance_criteria=["done"], context_refs=[],
                      project_id=project_id, inputs=inputs or {}, **task_kw)
    return make_envelope(task, sender="manager", receiver=f"cap:{capability}", correlation_id=task.task_id,
                         task_id=task.task_id, project_id=project_id, traceparent=new_traceparent())
