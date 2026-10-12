"""Agent runtime (Sprint 1 item 1.12): wraps one ``BaseAgent`` instance and does everything except ``handle``.

Message sequence per worker (all agent -> manager reports go through ``Bus.send_reply``)::

    start():  on_start() -> agent.register -> agent.heartbeat (now, then every heartbeat_s)
              -> subscribe "task.cancelled" events -> consume hmap.cap.<capability> (prefetch = max_slots)
    per task.assign delivery:
        duplicate (inbox seen / same execution already running) -> ack, skip
        no free slot / wrong capability -> task.ack(rejected) -> inbox record -> ack
        otherwise -> task.ack(accepted) -> task.started -> task.progress* -> task.result | error
                  -> inbox record -> ack            (the delivery is acked only after the reply was sent)
    stop():   DRAINING (heartbeat) -> wait for in-flight work (deadline) -> cooperative cancel -> hard cancel
              -> cancel consumers (unsettled deliveries are requeued) -> agent.deregister -> on_stop() -> OFFLINE

Dedup (research §24): ``inbox.seen`` is checked first and ``inbox.record`` happens after the reply was sent, so a
crash mid-handler leads to redelivery (at-least-once) rather than lost work; concurrent duplicates are guarded by
``execution_id``. Replies carry the incoming ``correlation_id``, a per-execution ``sequence_number`` and a child
``traceparent`` of the assignment.
"""

import asyncio
import contextlib
import itertools
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from hmap.core.bus.base import Bus, Delivery, Subscription, capability_queue
from hmap.core.bus.stores import InboxStore
from hmap.core.contracts import (
    AgentDeregister,
    AgentHeartbeat,
    AgentRegister,
    CapabilityDescriptor,
    Contract,
    DomainEvent,
    Envelope,
    ErrorPayload,
    EventType,
    TaskAck,
    TaskAssign,
    TaskCancel,
    TaskProgress,
    TaskResult,
    TaskStarted,
    make_envelope,
    utcnow,
)
from hmap.core.contracts.states import AgentState
from hmap.core.errors import Cancelled, ErrorCode, HmapError, classify, is_retryable
from hmap.core.ids import new_agent_instance_id
from hmap.core.llm.base import LLMClient
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.runtime.lifecycle import ACCEPTING_STATES, HEARTBEAT_STATES, AgentLifecycle
from hmap.core.tracing import bind_log_context, child_traceparent, get_logger, set_current_traceparent
from hmap.services.artifact.base import ArtifactStore
from hmap.services.context.base import ContextStore

PROTOCOL_VERSIONS = ["1.0"]
S = AgentState


def _local_only(llm: LLMClient) -> LLMClient:
    """The gateway's never-the-cloud copy (``Gateway.local_only``); duck-typed, since fakes never reach a cloud."""
    bind = getattr(llm, "local_only", None)
    if bind is None:
        return llm
    bound: LLMClient = bind()
    return bound


@dataclass
class _Execution:
    envelope: Envelope
    task: TaskAssign
    traceparent: str
    seq: "itertools.count[int]" = field(default_factory=lambda: itertools.count(1))
    ctx: AgentContext | None = None
    runner: "asyncio.Task[None] | None" = None
    shutdown: bool = False  # cancelled because the worker is stopping (not by the Manager)


class AgentWorker:
    """Hosts one agent instance: registration, heartbeats, consumption, dedup, replies, cancellation, draining."""

    def __init__(self, agent: BaseAgent, bus: Bus, llm: LLMClient, artifacts: ArtifactStore,
                 contexts: ContextStore, inbox: InboxStore, *, heartbeat_s: float = 5.0, agent_id: str | None = None,
                 capabilities: Sequence[str] | None = None, plugin: str | None = None,
                 drain_timeout_s: float = 30.0, cancel_grace_s: float = 2.0,
                 register_retry_delays_s: Sequence[float] = (0.5, 2.0, 5.0)) -> None:
        if not agent.name:
            raise ValueError(f"{type(agent).__name__} has no name")
        caps = tuple(capabilities) if capabilities is not None else tuple(agent.capabilities)
        if not caps:
            raise ValueError(f"agent {agent.name} serves no capability")
        unknown = set(caps) - set(agent.capabilities)
        if unknown:
            raise ValueError(f"agent {agent.name} does not declare {sorted(unknown)}")
        self.agent = agent
        self.bus = bus
        self.llm = llm
        self.artifacts = artifacts
        self.contexts = contexts
        self.inbox = inbox
        self.heartbeat_s = heartbeat_s
        self.agent_id = agent_id or new_agent_instance_id(agent.name)
        self.capabilities = caps
        self.plugin = plugin
        self.max_slots = max(1, int(agent.max_slots))
        self.drain_timeout_s = drain_timeout_s
        self.cancel_grace_s = cancel_grace_s
        self.register_retry_delays_s = tuple(register_retry_delays_s)
        self.consumer_id = f"agent:{agent.name}"  # stable across restarts -> redelivery after completion is deduped
        self.lifecycle = AgentLifecycle()
        self.log = get_logger("hmap.runtime.worker").bind(agent_id=self.agent_id, agent=agent.name)
        self._running: dict[str, _Execution] = {}
        self._recently_cancelled: deque[str] = deque(maxlen=512)
        self._idle = asyncio.Event()
        self._idle.set()
        self._command_subs: list[Subscription] = []
        self._event_sub: Subscription | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._started = False
        self._stopping = False
        self._stopped = asyncio.Event()

    # ------------------------------------------------------------------ introspection

    @property
    def state(self) -> AgentState:
        return self.lifecycle.state

    @property
    def available_slots(self) -> int:
        return max(0, self.max_slots - len(self._running))

    @property
    def current_execution_ids(self) -> list[str]:
        return list(self._running)

    # ------------------------------------------------------------------ start / stop

    async def start(self) -> None:
        if self._started:
            raise RuntimeError(f"worker {self.agent_id} already started")
        self._started = True
        try:
            await self.agent.on_start()
        except Exception as exc:
            self.lifecycle.to(S.FAILED, f"on_start failed: {exc!r}")
            raise
        self.lifecycle.to(S.REGISTERING, "on_start done")
        await self._register()
        try:
            self._event_sub = await self.bus.subscribe_events(EventType.TASK_CANCELLED.value, self._on_cancel_event)
            for cap in self.capabilities:
                self._command_subs.append(
                    await self.bus.consume_commands(cap, self._on_command, prefetch=self.max_slots))
        except Exception as exc:
            self.lifecycle.try_to(S.FAILED, f"consume failed: {exc!r}")
            await self._cancel_subscriptions()
            raise
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name=f"hmap-heartbeat:{self.agent_id}")
        self.log.info("agent started", capabilities=list(self.capabilities), max_slots=self.max_slots)

    async def stop(self, reason: str = "shutdown", *, timeout_s: float | None = None) -> None:
        """Drain gracefully: stop accepting, let in-flight work finish (up to the deadline), deregister, OFFLINE."""
        if self._stopping:
            await self._stopped.wait()
            return
        self._stopping = True
        if not self._started:
            self._stopped.set()
            return
        try:
            if self.state in ACCEPTING_STATES:
                self.lifecycle.to(S.DRAINING, reason)
                await self._send_heartbeat()
            await self._drain(self.drain_timeout_s if timeout_s is None else timeout_s)
            await self._cancel_subscriptions()
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._heartbeat_task
            if self.state in (S.DRAINING, S.FAILED):
                with contextlib.suppress(Exception):
                    await self._send(AgentDeregister(agent_id=self.agent_id, reason=reason),
                                     correlation_id=self.agent_id)
            try:
                await self.agent.on_stop()
            except Exception as exc:
                self.log.warning("on_stop failed", error=repr(exc))
            self.lifecycle.try_to(S.OFFLINE, reason)
            self.log.info("agent stopped", reason=reason, state=self.state.value)
        finally:
            self._stopped.set()

    async def __aenter__(self) -> "AgentWorker":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def _drain(self, timeout_s: float) -> None:
        if await self._wait_idle(timeout_s):
            return
        self.log.warning("drain deadline passed; cancelling in-flight work", executions=self.current_execution_ids)
        for exe in self._running.values():
            exe.shutdown = True
            if exe.ctx is not None:
                exe.ctx.cancelled.set()
        if await self._wait_idle(self.cancel_grace_s):
            return
        runners = [exe.runner for exe in self._running.values() if exe.runner is not None]
        for runner in runners:
            runner.cancel()  # unsettled deliveries are requeued when the consumer is cancelled below
        await asyncio.gather(*runners, return_exceptions=True)

    async def _wait_idle(self, timeout_s: float) -> bool:
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=max(0.0, timeout_s))
        except TimeoutError:
            return False
        return True

    async def _cancel_subscriptions(self) -> None:
        subs = [*self._command_subs, *([self._event_sub] if self._event_sub else [])]
        self._command_subs, self._event_sub = [], None
        for sub in subs:
            try:
                await sub.cancel()
            except Exception as exc:
                self.log.warning("subscription cancel failed", error=repr(exc))

    # ------------------------------------------------------------------ registration / heartbeat

    async def _register(self) -> None:
        msg = AgentRegister(
            agent_id=self.agent_id,
            endpoint=",".join(capability_queue(c) for c in self.capabilities),
            capabilities=[CapabilityDescriptor(name=c, version=self.agent.version,
                                               constraints={"max_concurrency": self.max_slots})
                          for c in self.capabilities],
            protocol_versions=list(PROTOCOL_VERSIONS), max_slots=self.max_slots, build_version=self.agent.version,
            plugin=self.plugin, is_stub=bool(self.agent.is_stub),
        )
        delays = iter(self.register_retry_delays_s)
        while True:
            try:
                await self._send(msg, correlation_id=self.agent_id)
            except Exception as exc:
                self.lifecycle.to(S.RECOVERING, f"register failed: {exc!r}")
                delay = next(delays, None)
                if delay is None:
                    self.lifecycle.to(S.FAILED, "registration retry budget exhausted")
                    raise
                self.log.warning("registration failed; retrying", error=repr(exc), delay_s=delay)
                await asyncio.sleep(delay)
                self.lifecycle.to(S.REGISTERING, "retry registration")
                continue
            self.lifecycle.to(S.AVAILABLE, "registration sent")
            return

    async def _heartbeat_loop(self) -> None:
        while True:
            await self._send_heartbeat()
            await asyncio.sleep(self.heartbeat_s)

    async def _send_heartbeat(self) -> None:
        state = self.state
        if state not in HEARTBEAT_STATES:
            return
        msg = AgentHeartbeat(agent_id=self.agent_id, state=state, observed_at=utcnow(),
                             available_slots=self.available_slots, current_execution_ids=self.current_execution_ids)
        try:
            await self._send(msg, correlation_id=self.agent_id)
        except Exception as exc:  # telemetry: never let a heartbeat failure kill the loop
            self.log.warning("heartbeat failed", error=repr(exc))

    async def _send(self, payload: Contract, *, correlation_id: str, exe: _Execution | None = None) -> None:
        if exe is None:
            env = make_envelope(payload, sender=self.agent_id, correlation_id=correlation_id)
        else:
            env = make_envelope(payload, sender=self.agent_id, receiver=exe.envelope.sender.agent_id,
                                correlation_id=correlation_id, task_id=exe.task.task_id,
                                execution_id=exe.task.execution_id,
                                project_id=exe.task.project_id or exe.envelope.project_id,
                                traceparent=exe.traceparent, sequence_number=next(exe.seq))
        await self.bus.send_reply(env)

    async def _reply(self, exe: _Execution, payload: Contract) -> None:
        await self._send(payload, correlation_id=exe.envelope.correlation_id, exe=exe)

    # ------------------------------------------------------------------ commands

    async def _on_command(self, delivery: Delivery) -> None:
        body = delivery.body
        if not isinstance(body, Envelope):
            await delivery.reject("domain event on a command queue")
            return
        try:
            payload = body.typed_payload()
        except (HmapError, ValueError) as exc:
            await delivery.reject(f"invalid payload: {exc}")
            return
        if isinstance(payload, TaskCancel):
            self._cancel_matching(payload.task_id, payload.execution_id, payload.reason)
            await delivery.ack()
        elif isinstance(payload, TaskAssign):
            await self._on_assign(delivery, body, payload)
        else:
            await delivery.reject(f"unsupported command {body.message_type}")

    async def _on_assign(self, delivery: Delivery, env: Envelope, task: TaskAssign) -> None:
        log = self.log.bind(task_id=task.task_id, execution_id=task.execution_id, message_id=env.message_id)
        if await self.inbox.seen(self.consumer_id, env.message_id):
            log.info("duplicate delivery skipped (inbox)")
            await delivery.ack()
            return
        if task.execution_id in self._running:
            log.info("duplicate delivery skipped (execution already running)")
            await delivery.ack()
            return
        if self.state not in ACCEPTING_STATES:
            # Leave it unsettled: it is requeued (redelivered=True) to another consumer when we cancel our consumer.
            log.info("not accepting work; delivery left for redelivery", state=self.state.value)
            return
        exe = _Execution(envelope=env, task=task, traceparent=child_traceparent(env.traceparent))
        reject_reason: str | None = None
        if task.capability not in self.capabilities:
            reject_reason = f"capability {task.capability} not served by {self.agent.name}"
        elif len(self._running) >= self.max_slots:
            reject_reason = "no free slot"
        if reject_reason is not None or task.execution_id in self._recently_cancelled:
            await self._settle_without_running(delivery, exe, reject_reason)
            return
        # No await between the duplicate/slot checks above and this insertion.
        exe.ctx = self._make_context(exe, log)
        self._running[task.execution_id] = exe
        self._idle.clear()
        self.lifecycle.try_to(S.BUSY, f"accepted {task.execution_id}")
        exe.runner = asyncio.create_task(self._execute(delivery, exe), name=f"hmap-exec:{task.execution_id}")
        try:
            await asyncio.wait({exe.runner})
        except asyncio.CancelledError:  # our consumer was cancelled (crash / connection loss simulation)
            exe.runner.cancel()
            raise

    def _make_context(self, exe: _Execution, log: Any) -> AgentContext:
        task = exe.task

        async def progress(percent: int, summary: str) -> None:  # at-most-once telemetry
            try:
                await self._reply(exe, TaskProgress(execution_id=task.execution_id, percent=percent, summary=summary))
            except Exception as exc:
                log.warning("progress not sent", error=repr(exc))

        # a local-only project (doc 02 §2.5): this task's client can never reach a cloud model
        llm = self.llm if task.cloud_ok else _local_only(self.llm)
        return AgentContext(task=task, agent_id=self.agent_id, llm=llm, artifacts=self.artifacts,
                            context=self.contexts, logger=log, _progress=progress)

    async def _settle_without_running(self, delivery: Delivery, exe: _Execution, reason: str | None) -> None:
        payload: Contract
        if reason is None:  # cancelled before it arrived (out-of-order)
            payload = ErrorPayload(execution_id=exe.task.execution_id, error_code=ErrorCode.CANCELLED,
                                   message="execution was cancelled before it started", retryable=False)
        else:
            payload = TaskAck(execution_id=exe.task.execution_id, decision="rejected", reason=reason,
                              available_slots=self.available_slots)
        try:
            await self._reply(exe, payload)
        except Exception as exc:
            self.log.warning("could not send rejection; requeueing", error=repr(exc))
            with contextlib.suppress(Exception):
                await delivery.nack(requeue=True)
            return
        await self.inbox.record(self.consumer_id, exe.envelope.message_id)
        await delivery.ack()

    async def _execute(self, delivery: Delivery, exe: _Execution) -> None:
        task, ctx = exe.task, exe.ctx
        assert ctx is not None
        log = ctx.logger
        set_current_traceparent(exe.traceparent)
        bind_log_context(agent_id=self.agent_id, task_id=task.task_id, execution_id=task.execution_id,
                         message_id=exe.envelope.message_id)
        try:
            await self._reply(exe, TaskAck(execution_id=task.execution_id, decision="accepted",
                                           available_slots=self.available_slots))
            await self._reply(exe, TaskStarted(execution_id=task.execution_id))
            outcome = await self._run_handler(exe, ctx, log)
            await self._reply(exe, outcome)
        except asyncio.CancelledError:
            log.warning("execution hard-cancelled; delivery left unsettled for redelivery")
            raise
        except Exception as exc:  # could not report (bus down): let the broker redeliver
            log.error("reply failed; nacking delivery", error=repr(exc))
            with contextlib.suppress(Exception):
                await delivery.nack(requeue=True)
        else:
            await self.inbox.record(self.consumer_id, exe.envelope.message_id)
            await delivery.ack()
        finally:
            self._running.pop(task.execution_id, None)
            if not self._running:
                self._idle.set()
                self.lifecycle.try_to(S.AVAILABLE, f"finished {task.execution_id}")

    async def _run_handler(self, exe: _Execution, ctx: AgentContext, log: Any) -> TaskResult | ErrorPayload:
        task = exe.task
        try:
            timeout = None
            if task.deadline is not None:
                timeout = max(0.0, (task.deadline - utcnow()).total_seconds())
            async with asyncio.timeout(timeout):
                result = await self.agent.handle(task, ctx)
            if not isinstance(result, TaskResult):
                raise HmapError(f"handler returned {type(result).__name__}, expected TaskResult")
            if result.execution_id != task.execution_id:
                result = result.model_copy(update={"execution_id": task.execution_id})
            return result
        except Exception as exc:
            code = classify(exc)
            retryable = exc.retryable if isinstance(exc, HmapError) else is_retryable(code)
            message = str(exc) or type(exc).__name__
            if isinstance(exc, Cancelled) and exe.shutdown:
                code, retryable, message = ErrorCode.AGENT_UNAVAILABLE, True, "agent shutting down"
            log.warning("handler failed", error_code=code.value, retryable=retryable, error=repr(exc))
            return ErrorPayload(execution_id=task.execution_id, error_code=code, message=message[:2000],
                                retryable=retryable)

    # ------------------------------------------------------------------ cancellation

    async def _on_cancel_event(self, delivery: Delivery) -> None:
        body = delivery.body
        try:
            if isinstance(body, DomainEvent):
                execution_id = body.data.get("execution_id")
                self._cancel_matching(body.aggregate_id, execution_id if isinstance(execution_id, str) else None,
                                      str(body.data.get("reason", "task cancelled")))
        finally:
            await delivery.ack()

    def _cancel_matching(self, task_id: str, execution_id: str | None, reason: str) -> None:
        if execution_id:
            self._recently_cancelled.append(execution_id)
        for exe in self._running.values():
            if (exe.task.execution_id == execution_id) if execution_id else (exe.task.task_id == task_id):
                self.log.info("cancellation requested", execution_id=exe.task.execution_id, reason=reason)
                if exe.ctx is not None:
                    exe.ctx.cancelled.set()
