"""Observability (items 4.15, 4.17, plan D17): one task = one trace (Manager -> bus -> agent -> model), metrics on
``/metrics``, nothing private in spans or metrics, and no-ops when tracing is off."""

import asyncio
import re
import time
from collections.abc import Iterator
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hmap import obs
from hmap.api.app import create_app
from hmap.core.config import Settings
from hmap.core.contracts import TaskAssign, TaskResult
from hmap.core.llm import FakeLLM, Gateway
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.runtime.discovery import discover
from hmap.obs import metrics
from hmap.system import HmapSystem, SystemConfig
from tests.api.helpers import signed_in

SECRET_PROMPT = "PRIVATE-PROMPT-7f3a: the student's essay says the password is hunter2"
SECRET_DOC = "CONFIDENTIAL-DOC-91bc quarterly figures"
FAKE_KEY = "gsk_" + "A" * 48
KEY_PATTERNS = [re.compile(r"gsk_[A-Za-z0-9]{20,}"), re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
                re.compile(r"sk-[A-Za-z0-9]{20,}")]


class Summariser(BaseAgent):
    name = "summariser"
    capabilities: ClassVar[tuple[str, ...]] = ("notes.summarise",)

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        reply = await ctx.llm.generate("fast", [{"role": "user", "content": f"{SECRET_PROMPT} {FAKE_KEY}"}])
        ref = await ctx.put_json({"summary": reply.text, "doc": SECRET_DOC}, artifact_type="notes")
        return ctx.result([ref], summary="summarised")


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    exp = InMemorySpanExporter()
    assert obs.configure(service_name="hmap-test", exporter=exp, batch=False)
    yield exp
    obs.shutdown()


def test_tracing_is_a_no_op_when_off() -> None:
    obs.shutdown()
    assert not obs.enabled()
    with obs.span("x", attrs={"a": 1}) as s:
        s.set("b", 2)
        s.error(RuntimeError("boom"))
        assert s.traceparent() is None and not s.recording
    assert obs.current_traceparent() is None
    tp = obs.task_traceparent("T-1")
    assert obs.trace_id_of(tp) == obs.task_trace_id("T-1") and obs.task_trace_id("T-1") != obs.task_trace_id("T-2")
    assert obs.configure(service_name="x", endpoint="") is False      # no endpoint, no exporter: stays off


def test_safe_attrs_drop_text_and_secrets() -> None:
    attrs = obs.safe_attrs({"hmap.task_id": "T-1", "gen_ai.usage.input_tokens": 12, "prompt": "hi",
                            "message_text": "x", "hmap.note": "y" * 500, "api_key": "k", "ok": [1, "a"],
                            "body": "secret", "nested": {"a": 1}, "none": None})
    assert attrs == {"hmap.task_id": "T-1", "gen_ai.usage.input_tokens": 12, "ok": [1, "a"]}


async def test_one_task_is_one_trace_from_manager_to_agent_to_model(exporter: InMemorySpanExporter,
                                                                   tmp_path) -> None:
    llm = Gateway(Settings(llm_mode="fake"), fake=FakeLLM(default="a short summary"))
    system = HmapSystem.in_memory(artifact_root=tmp_path, llm=llm, plugins=[
        *discover(), Plugin(name="notes", agents=[Summariser], priority=100)],
        config=SystemConfig(heartbeat_s=0.1, watchdog_interval_s=0.05))
    await system.start()
    try:
        m = system.manager
        pid = await m.create_project("traced")
        task_id = await m.create_task(pid, "notes.summarise", "summarise the notes")
        for _ in range(200):
            if (await m.get_task(task_id))["state"] == "COMPLETED":
                break
            await asyncio.sleep(0.02)
        assert (await m.get_task(task_id))["state"] == "COMPLETED"
        await asyncio.sleep(0.1)
    finally:
        await system.stop()
    spans = [s for s in exporter.get_finished_spans()
             if s.context.trace_id == int(obs.task_trace_id(task_id), 16)]
    names = {s.name for s in spans}
    assert {"manager.assign notes.summarise", "send hmap.cap.notes.summarise", "process hmap.cap.notes.summarise",
            "agent.handle notes.summarise", "chat fast", "manager.handle task.result"} <= names
    by_name = {s.name: s for s in spans}
    root = by_name["manager.assign notes.summarise"]
    assert root.parent is None and root.attributes["hmap.task_id"] == task_id
    process, handle, chat = (by_name["process hmap.cap.notes.summarise"], by_name["agent.handle notes.summarise"],
                             by_name["chat fast"])
    assert process.parent.span_id == root.context.span_id                # the assignment's traceparent
    assert handle.parent.span_id == process.context.span_id
    assert chat.parent.span_id == handle.context.span_id
    assert chat.attributes["gen_ai.response.model"] == "fake" and chat.attributes["gen_ai.usage.output_tokens"] > 0
    result = by_name["manager.handle task.result"]
    assert result.parent.span_id == handle.context.span_id               # the reply continues the trace
    # D17: nothing private in any exported span
    blob = " ".join(f"{s.name} {dict(s.attributes or {})} {[(e.name, dict(e.attributes or {})) for e in s.events]}"
                    for s in exporter.get_finished_spans())
    for secret in (SECRET_PROMPT, "hunter2", SECRET_DOC, "a short summary", FAKE_KEY):
        assert secret not in blob
    assert not any(p.search(blob) for p in KEY_PATTERNS)
    text = metrics.exposition()[0].decode()
    for secret in (SECRET_PROMPT, SECRET_DOC, FAKE_KEY, pid, task_id):
        assert secret not in text
    assert not any(p.search(text) for p in KEY_PATTERNS)
    assert 'hmap_llm_calls_total' in text or "hmap_agent_handle_seconds" in text


def test_metrics_endpoint_and_sampler(tmp_path) -> None:
    system = HmapSystem.in_memory(artifact_root=tmp_path, config=SystemConfig(
        heartbeat_s=0.1, watchdog_interval_s=0.05, metrics_interval_s=0.05))
    with TestClient(create_app(system, run_agents=True)) as client:
        signed_in(client)
        pid = client.post("/api/projects", json={"name": "m"}).json()["project_id"]
        client.post(f"/api/projects/{pid}/tasks", json={"capability": "echo", "objective": "hi"})
        end = time.time() + 10
        body = ""
        while time.time() < end:
            body = client.get("/metrics").text
            if "hmap_agent_heartbeat_age_seconds{" in body and 'hmap_task_transitions_total{capability="echo",' \
                    'state="COMPLETED"}' in body:
                break
            time.sleep(0.05)
        r = client.get("/metrics")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    for name in ("hmap_queue_depth", "hmap_tasks", "hmap_dead_lettered_tasks", "hmap_bus_dlq_messages",
                 "hmap_agent_heartbeat_age_seconds", "hmap_process_rss_bytes", "hmap_system_memory_available_bytes",
                 "hmap_task_transitions_total", "hmap_agent_handle_seconds", "hmap_dedup_hits_total",
                 "hmap_llm_latency_seconds"):
        assert name in body, name
    assert 'hmap_task_transitions_total{capability="echo",state="COMPLETED"}' in body
    assert pid not in body


async def test_sampler_counts_dead_letters_and_survives_errors() -> None:
    class Bus:
        async def queue_depths(self):
            return {"hmap.cap.echo": 3}

        async def dead_letters(self):
            return [object(), object()]

    class Store:
        async def list_tasks(self, *, states=None):
            raise RuntimeError("db down")

    class Registry:
        async def list(self):
            return []

    before = metrics.SAMPLE_ERRORS._value.get()
    await metrics.Sampler(bus=Bus(), store=Store(), registry=Registry()).sample()
    assert metrics.SAMPLE_ERRORS._value.get() == before + 1
    assert metrics.QUEUE_DEPTH.labels("hmap.cap.echo")._value.get() == 3
    assert metrics.BUS_DLQ._value.get() == 2


async def test_a_recently_lost_agent_keeps_its_heartbeat_age() -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    now = datetime.now(UTC)

    class Bus:
        async def queue_depths(self):
            return {"hmap.cap.echo": 0, "hmap.events.tmp.abc": 4}

        async def dead_letters(self):
            return []

    class Store:
        async def list_tasks(self, *, states=None):
            return []

    agents = [SimpleNamespace(agent_id="echo-aaaa1111", state="OFFLINE", last_heartbeat=now - timedelta(seconds=45)),
              SimpleNamespace(agent_id="echo-bbbb2222", state="OFFLINE", last_heartbeat=now - timedelta(hours=2)),
              SimpleNamespace(agent_id="echo-cccc3333", state="AVAILABLE", last_heartbeat=now)]

    class Registry:
        async def list(self):
            return agents

    await metrics.Sampler(bus=Bus(), store=Store(), registry=Registry()).sample()
    text = metrics.exposition()[0].decode()
    lost = metrics.AGENT_HEARTBEAT_AGE.labels("echo-aaaa1111", "echo", "OFFLINE")._value.get()
    assert lost > 30                                                     # HmapAgentHeartbeatExpired fires
    assert "echo-bbbb2222" not in text and 'queue="hmap.events.tmp.abc"' not in text
