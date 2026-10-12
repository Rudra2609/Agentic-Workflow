"""``PostgresContextStore`` + ``PostgresRegistry`` + ``PgArtifactMetadata``. Context scenarios are ported from
``tests/services/context/test_context_store.py``; the registry tests are imported from
``tests/services/registry/test_registry.py`` and re-run against Postgres via the ``registry`` fixture below."""

import asyncio
from datetime import timedelta

import pytest

from hmap.core.contracts import ArtifactRef, ContextRef
from hmap.core.errors import ArtifactConflict, AuthorizationError, ErrorCode
from hmap.db import Database
from hmap.services.artifact.pg_meta import PgArtifactMetadata
from hmap.services.context.memory import ContextNotFound, content_sha256
from hmap.services.context.pg import PostgresContextStore
from hmap.services.registry.pg import PostgresRegistry
from tests.services.registry.test_registry import (  # noqa: F401  (re-collected here against Postgres)
    Clock,
    hb,
    reg,
    test_deregister_removes,
    test_expire_leases_marks_offline,
    test_expire_leases_with_explicit_now,
    test_find_candidates_matching_and_ordering,
    test_heartbeat_renews_lease_and_updates_slots,
    test_register_negotiates_and_leases,
    test_register_without_shared_version_is_rejected,
    test_reregister_bumps_version,
    test_stub_only_is_still_a_candidate,
)

pytestmark = pytest.mark.integration


# ================================================================== context


@pytest.fixture
def contexts(db: Database) -> PostgresContextStore:
    return PostgresContextStore(db)


async def test_create_and_get_v1(contexts: PostgresContextStore) -> None:
    ref = await contexts.create("P1", {"goal": "chat server"}, author="manager")
    snap = await contexts.get(ref)
    assert ref.version == 1 and ref.context_id.startswith("CTX-")
    assert snap.parent_version is None and snap.author == "manager" and snap.project_id == "P1"
    assert snap.content == {"goal": "chat server"} and snap.change_summary == "initial"
    assert snap.content_sha256 == content_sha256({"goal": "chat server"})


async def test_versions_are_immutable_snapshots(contexts: PostgresContextStore) -> None:
    content = {"goal": "chat", "constraints": ["stdlib"]}
    v1 = await contexts.create("P1", content, author="manager", context_id="CTX-42")
    content["constraints"].append("mutated after create")
    v2 = await contexts.create("P1", {"goal": "chat v2"}, author="planner", context_id="CTX-42",
                               change_summary="new goal")
    assert (v1, v2) == (ContextRef(context_id="CTX-42", version=1), ContextRef(context_id="CTX-42", version=2))
    s1, s2 = await contexts.get(v1), await contexts.get(v2)
    assert s1.content == {"goal": "chat", "constraints": ["stdlib"]}
    assert (s2.parent_version, s2.author, s2.change_summary) == (1, "planner", "new goal")
    s1.content["goal"] = "edited copy"
    assert (await contexts.get(v1)).content["goal"] == "chat"
    assert [s.version for s in await contexts.history("CTX-42")] == [1, 2]


async def test_is_stale_and_latest(contexts: PostgresContextStore) -> None:
    v1 = await contexts.create("P1", {"a": 1}, author="m")
    assert not await contexts.is_stale(v1)
    v2 = await contexts.create("P1", {"a": 2}, author="m", context_id=v1.context_id)
    assert await contexts.is_stale(v1) and not await contexts.is_stale(v2)
    assert await contexts.latest(v1.context_id) == v2


async def test_missing_and_cross_project(contexts: PostgresContextStore) -> None:
    with pytest.raises(ContextNotFound) as err:
        await contexts.get(ContextRef(context_id="CTX-x", version=1))
    assert err.value.code == ErrorCode.MISSING_CONTEXT
    with pytest.raises(ContextNotFound):
        await contexts.latest("CTX-x")
    ref = await contexts.create("P1", {}, author="m")
    with pytest.raises(ContextNotFound):
        await contexts.get(ContextRef(context_id=ref.context_id, version=2))
    with pytest.raises(AuthorizationError):
        await contexts.create("P2", {}, author="m", context_id=ref.context_id)
    assert await contexts.history("CTX-x") == []


async def test_non_json_content_rejected(contexts: PostgresContextStore) -> None:
    with pytest.raises(TypeError):
        await contexts.create("P1", {"x": object()}, author="m")


async def test_concurrent_writers_get_consecutive_versions(contexts: PostgresContextStore) -> None:
    await contexts.create("P1", {"n": 0}, author="m", context_id="CTX-C")
    refs = await asyncio.gather(*(contexts.create("P1", {"n": i}, author=f"w{i}", context_id="CTX-C")
                                  for i in range(1, 11)))
    assert sorted(r.version for r in refs) == list(range(2, 12))
    history = await contexts.history("CTX-C")
    assert [(s.version, s.parent_version) for s in history] == [(v, v - 1 if v > 1 else None) for v in range(1, 12)]


# ================================================================== registry


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def registry(db: Database, clock: Clock) -> PostgresRegistry:
    return PostgresRegistry(db, lease_s=30, clock=clock)


def test_invalid_lease(db: Database) -> None:
    with pytest.raises(ValueError):
        PostgresRegistry(db, lease_s=0)


async def test_concurrent_heartbeats_do_not_lose_updates(registry: PostgresRegistry, clock: Clock) -> None:
    await registry.register(reg("a1", "echo", slots=4))
    await asyncio.gather(*(registry.heartbeat(hb(clock, "a1", executions=(f"E-{i}",))) for i in range(10)))
    rec = await registry.get("a1")
    assert rec is not None and rec.state_version == 1 and len(rec.current_execution_ids) == 1
    assert rec.lease_until == clock.now + timedelta(seconds=30)


# ================================================================== artifact metadata


def _art(artifact_id: str, version: int, project: str = "P1", minute: int = 0) -> ArtifactRef:
    from datetime import UTC, datetime
    return ArtifactRef(artifact_id=artifact_id, artifact_type="report", version=version, uri=f"file://{artifact_id}",
                       sha256=f"{version:064x}", media_type="text/plain", size_bytes=10, created_by="agent",
                       created_at=datetime(2026, 10, 1, 9, minute, tzinfo=UTC), access_scope=project,
                       supersedes=version - 1 if version > 1 else None)


async def test_artifact_metadata_round_trip_scope_and_conflict(db: Database) -> None:
    meta = PgArtifactMetadata(db)
    assert await meta.next_version("ART-1") == 1
    a1 = await meta.record(_art("ART-1", 1, minute=1))
    a2 = await meta.record(_art("ART-1", 2, minute=3))
    b1 = await meta.record(_art("ART-0", 1, minute=2))
    await meta.record(_art("ART-9", 1, project="P2"))
    with pytest.raises(ArtifactConflict):
        await meta.record(_art("ART-1", 2))                   # (artifact_id, version) is write-once
    assert await meta.get("ART-1", 1, project_id="P1") == a1
    assert await meta.get("ART-1", 1, project_id="P2") is None  # project-scoped
    assert await meta.latest("ART-1", project_id="P1") == a2
    assert await meta.latest("ART-9", project_id="P1") is None
    assert await meta.next_version("ART-1") == 3
    assert await meta.list("P1") == [a1, b1, a2]
