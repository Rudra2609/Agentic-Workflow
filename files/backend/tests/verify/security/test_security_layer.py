"""Security layer (Sprint 6 items 6.20, 6.15, 6.14): service tokens, signed messages, the policy table, the audit
log, key rotation without downtime, expiry and revocation. In memory: no infra."""

import asyncio
import os
import stat
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from hmap.core import policy
from hmap.core.contracts import (
    AgentHeartbeat,
    AgentRef,
    AgentState,
    Envelope,
    TaskAssign,
    TaskResult,
    make_envelope,
)
from hmap.core.contracts.capabilities import ECHO
from hmap.core.contracts.common import utcnow
from hmap.core.contracts.examples import artifact
from hmap.core.llm import FakeLLM
from hmap.system import HmapSystem, SystemConfig


@pytest.fixture
def ring(tmp_path: Path) -> policy.Keyring:
    return policy.Keyring.from_settings(path=tmp_path / "keys.json")


# ------------------------------------------------------------------------------------------------ tokens (unit)


def test_keyring_file_is_private_and_shared(tmp_path: Path) -> None:
    a = policy.Keyring.from_settings(path=tmp_path / "keys.json")
    b = policy.Keyring.from_settings(path=tmp_path / "keys.json")
    assert a.keys == b.keys and len(a.keys) == 1                       # one seeded dev key, every process agrees
    assert stat.S_IMODE(os.stat(tmp_path / "keys.json").st_mode) == 0o600


def test_env_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    from hmap.core.config import Settings

    monkeypatch.setenv("HMAP_AGENT_SECRETS", "k2:new-secret,k1:old-secret")
    ring = policy.Keyring.from_settings(Settings.from_env())
    assert [k for k, _ in ring.keys] == ["k2", "k1"] and ring.path is None
    assert "new-secret" not in repr(Settings.from_env())                # SecretStr: never printed


def test_token_lifecycle(ring: policy.Keyring) -> None:
    tok = policy.issue_token(ring, "agent-a", ttl_s=60)
    assert policy.check_token(ring, tok, "agent-a").allowed
    assert not policy.check_token(ring, tok, "agent-b").allowed                       # bound to the agent
    assert policy.check_token(ring, tok, "agent-a", now=time.time() + 120).reason == "token expired"
    assert not policy.check_token(ring, tok.replace(".", "x", 1), "agent-a").allowed
    assert not policy.check_token(ring, None, "agent-a").allowed
    old = ring.keys[0][0]
    ring.rotate()
    assert policy.check_token(ring, tok, "agent-a").allowed                           # old key still verifies
    ring.retire(old)
    assert policy.check_token(ring, tok, "agent-a").reason == "unknown or retired signing key"
    tok2 = policy.issue_token(ring, "agent-a", ttl_s=60)
    ring.revoke("agent-a")
    assert policy.check_token(ring, tok2, "agent-a").reason == "agent revoked"
    ring.unrevoke("agent-a")
    assert policy.check_token(ring, tok2, "agent-a").allowed
    with pytest.raises(ValueError):
        ring.retire(ring.keys[0][0])                                                  # never the last key


def test_signed_envelopes(ring: policy.Keyring) -> None:
    signer = policy.Signer(ring, ttl_s=60)
    hb = AgentHeartbeat(agent_id="agent-a", state=AgentState.AVAILABLE, observed_at=utcnow(), available_slots=1,
                        current_execution_ids=[])
    env = make_envelope(hb, sender="agent-a", correlation_id="c")
    env.auth = signer.sign(env)
    assert policy.check_auth(ring, env).allowed
    changed = env.model_copy(update={"payload": {**env.payload, "available_slots": 9}})
    assert "forged or changed" in policy.check_auth(ring, changed).reason
    other = env.model_copy(update={"sender": AgentRef(agent_id="agent-b")})
    assert not policy.check_auth(ring, other).allowed
    assert policy.check_auth(ring, env.model_copy(update={"auth": None})).reason == "message is not signed"
    assert "v1." in (env.auth or "") and signer.token("agent-a") not in (env.auth or "")   # the token never travels


def test_signer_renews_and_follows_rotation(ring: policy.Keyring) -> None:
    signer = policy.Signer(ring, ttl_s=100)
    t1 = signer.token("a", now=1000.0)
    assert signer.token("a", now=1040.0) == t1                       # before half-life: same token
    assert signer.token("a", now=1060.0) != t1                       # renewed at half-life
    kid = ring.rotate()
    assert signer.token("a", now=1061.0).split(".")[1] == kid        # switches to the newest key


def test_rate_limiter_and_content_sniffing() -> None:
    clock = [0.0]
    rl = policy.RateLimiter(rate=1.0, burst=3, clock=lambda: clock[0])
    assert [rl.allow("u") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("other")
    clock[0] = 1.5
    assert rl.allow("u")
    assert policy.content_matches("application/pdf", b"%PDF-1.7 ...")
    assert not policy.content_matches("application/pdf", b"MZ\x90\x00 an executable")
    assert not policy.content_matches("text/plain", b"abc\x00def")
    assert policy.content_matches("text/plain", "héllo".encode())
    assert policy.fingerprint("secret") != "secret" and len(policy.fingerprint("secret")) == 8


# ------------------------------------------------------------------------------------------------ on the bus


@pytest.fixture
async def system(tmp_path: Path) -> AsyncIterator[HmapSystem]:
    policy.install(keyring=policy.Keyring.from_settings(path=tmp_path / "keys.json"))
    policy.AUDIT.entries.clear()
    s = HmapSystem.in_memory(llm=FakeLLM(default=None), config=SystemConfig(heartbeat_s=0.2,
                                                                            watchdog_interval_s=0.05))
    await s.start(with_agents=True)
    try:
        yield s
    finally:
        await s.stop()
        policy.install(keyring=policy.Keyring.from_settings())        # back to the default dev keyring


async def wait_task(s: HmapSystem, task_id: str, timeout: float = 15.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        t = await s.manager.get_task(task_id)
        if t["state"] in ("COMPLETED", "FAILED", "DEAD_LETTERED"):
            return t
        await asyncio.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish")


async def denied(rule: str, message_type: str, timeout: float = 5.0, sender: str | None = None) -> policy.AuditEntry:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for e in await policy.AUDIT.recent(50):
            if e.decision == "deny" and e.rule == rule and e.message_type == message_type \
                    and (sender is None or e.sender == sender):
                return e
        await asyncio.sleep(0.02)
    raise AssertionError(f"no audited refusal {rule} / {message_type}")


async def test_existing_agents_keep_working_and_forgeries_are_refused(system: HmapSystem) -> None:
    pid = await system.manager.create_project("sec")
    ok = await system.manager.create_task(pid, ECHO, "hello")
    assert (await wait_task(system, ok))["state"] == "COMPLETED"           # seeded tokens: nothing else to set up
    registered = [e for e in await policy.AUDIT.recent(500) if e.message_type == "agent.register"]
    assert registered and all(e.decision == "allow" for e in registered)

    # a long task, so an execution is in flight while we attack it
    victim = await system.manager.create_task(pid, ECHO, "slow", inputs={"stub_delay_s": 1.5})
    while not (await system.manager.get_task(victim)).get("active_execution_id"):
        await asyncio.sleep(0.02)
    t = await system.manager.get_task(victim)
    exe = str(t["active_execution_id"])
    result = TaskResult(execution_id=exe, outcome="success", artifact_refs=[artifact("echo")], summary="forged")

    # 1. an unsigned message (e.g. from anything else on the bus)
    raw = make_envelope(result, sender="echo-intruder", correlation_id=pid, task_id=victim, execution_id=exe)
    await system.bus.send_reply(raw.model_copy(update={"auth": None}))
    await denied("auth", "task.result")
    # 2. correctly signed, but the execution belongs to another agent
    await system.bus.send_reply(make_envelope(result, sender="echo-intruder", correlation_id=pid, task_id=victim,
                                              execution_id=exe))
    entry = await denied("assigned", "task.result")
    assert entry.sender == "echo-intruder" and entry.task_id == victim and entry.enforced
    assert entry.reason == "the sender is not a registered agent"
    # 2b. a registered agent of ANOTHER capability reporting on this step
    from hmap.core.contracts import AgentRegister, CapabilityDescriptor

    reg = AgentRegister(agent_id="rogue-1", endpoint="q", capabilities=[CapabilityDescriptor(name="rogue.op",
                        version="1")], protocol_versions=["1.0"], max_slots=1, build_version="1")
    await system.bus.send_reply(make_envelope(reg, sender="rogue-1", correlation_id="c"))
    for _ in range(100):
        if await system.manager.registry.get("rogue-1"):
            break
        await asyncio.sleep(0.02)
    await system.bus.send_reply(make_envelope(result, sender="rogue-1", correlation_id=pid, task_id=victim,
                                              execution_id=exe))
    entry = await denied("assigned", "task.result", sender="rogue-1")
    assert entry.reason == "the agent did not register capability echo"
    # 3. a heartbeat that speaks for another agent
    hb = AgentHeartbeat(agent_id="someone-else", state=AgentState.AVAILABLE, observed_at=utcnow(), available_slots=1,
                        current_execution_ids=[exe])
    await system.bus.send_reply(make_envelope(hb, sender="echo-intruder", correlation_id="c"))
    await denied("identity", "agent.heartbeat")
    # 4. agents may not send commands to the Manager
    assign = TaskAssign(task_id=victim, execution_id=exe, capability=ECHO, objective="x", acceptance_criteria=[],
                        context_refs=[])
    await system.bus.send_reply(make_envelope(assign, sender="echo-intruder", receiver="manager", correlation_id="c"))
    await denied("table", "task.assign")
    # 5. a signed message changed in transit
    signed = make_envelope(result, sender="echo-intruder", correlation_id=pid, task_id=victim, execution_id=exe)
    await system.bus.send_reply(signed.model_copy(update={"payload": {**signed.payload, "summary": "changed"}}))
    await denied("auth", "task.result")

    done = await wait_task(system, victim)
    assert done["state"] == "COMPLETED"
    final = [e for e in done["executions"] if e["status"] == "SUCCEEDED"]  # type: ignore[attr-defined]
    refs = final[-1]["result_refs"]
    assert refs and all(r["artifact_id"] != "echo" for r in refs)        # the real agent's result, not ours


async def echo_agent(s: HmapSystem) -> object:
    for _ in range(250):
        found = [a for a in await s.manager.registry.list() if ECHO in a.capabilities]
        if found:
            return found[0]
        await asyncio.sleep(0.02)
    raise AssertionError("echo agent never registered")


async def test_commands_only_from_the_manager(system: HmapSystem) -> None:
    pid = await system.manager.create_project("cmd")
    assign = TaskAssign(task_id="T-rogue", execution_id="E-rogue", capability=ECHO, objective="run this",
                        acceptance_criteria=[], context_refs=[], project_id=pid)
    agent = await echo_agent(system)
    await system.bus.send_command(ECHO, make_envelope(assign, sender="not-the-manager", receiver=agent.agent_id,  # type: ignore[attr-defined]
                                                     
                                                      correlation_id="c"))
    entry = await denied("table", "task.assign")
    assert entry.sender == "not-the-manager"
    forged = make_envelope(assign, sender="manager", receiver=agent.agent_id, correlation_id="c")
    await system.bus.send_command(ECHO, forged.model_copy(update={"auth": None}))
    await denied("auth", "task.assign")


async def test_rotation_without_downtime_and_revocation(system: HmapSystem) -> None:
    ring = policy.signer().keyring
    pid = await system.manager.create_project("rotate")
    slow = await system.manager.create_task(pid, ECHO, "spans the rotation", inputs={"stub_delay_s": 0.6})
    await asyncio.sleep(0.2)
    old = ring.keys[0][0]
    new = ring.rotate()                                   # while the task runs
    t2 = await system.manager.create_task(pid, ECHO, "after rotation")
    assert (await wait_task(system, slow))["state"] == "COMPLETED"
    assert (await wait_task(system, t2))["state"] == "COMPLETED"
    ring.retire(old)                                      # every sender already moved to the new key
    t3 = await system.manager.create_task(pid, ECHO, "old key retired")
    assert (await wait_task(system, t3))["state"] == "COMPLETED"
    assert ring.keys[0][0] == new and len(ring.keys) == 1

    agent = await echo_agent(system)
    ring.revoke(agent.agent_id)
    hb = AgentHeartbeat(agent_id=agent.agent_id, state=AgentState.AVAILABLE, observed_at=utcnow(), available_slots=1,
                        current_execution_ids=[])
    await system.bus.send_reply(make_envelope(hb, sender=agent.agent_id, correlation_id="c"))
    entry = await denied("auth", "agent.heartbeat")
    assert entry.reason == "agent revoked"
    ring.unrevoke(agent.agent_id)


async def test_audit_only_mode(system: HmapSystem, monkeypatch: pytest.MonkeyPatch) -> None:
    system.manager.policy.enforce = False
    hb = AgentHeartbeat(agent_id="ghost", state=AgentState.AVAILABLE, observed_at=utcnow(), available_slots=1,
                        current_execution_ids=[])
    env = Envelope.model_validate(make_envelope(hb, sender="ghost", correlation_id="c").model_dump()
                                  | {"auth": None})
    await system.bus.send_reply(env)
    entry = await denied("auth", "agent.heartbeat", sender="ghost")
    assert entry.enforced is False
