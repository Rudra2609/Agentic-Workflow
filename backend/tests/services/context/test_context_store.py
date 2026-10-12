import pytest

from hmap.core.contracts import ContextRef
from hmap.core.errors import AuthorizationError, ErrorCode
from hmap.services.context.memory import ContextNotFound, InMemoryContextStore, content_sha256


async def test_create_and_get_v1() -> None:
    store = InMemoryContextStore()
    ref = await store.create("P1", {"goal": "chat server"}, author="manager")
    snap = await store.get(ref)
    assert ref.version == 1 and ref.context_id.startswith("CTX-")
    assert snap.parent_version is None and snap.author == "manager" and snap.project_id == "P1"
    assert snap.content == {"goal": "chat server"}
    assert snap.content_sha256 == content_sha256({"goal": "chat server"})


async def test_versions_are_immutable_snapshots() -> None:
    store = InMemoryContextStore()
    content = {"goal": "chat", "constraints": ["stdlib"]}
    v1 = await store.create("P1", content, author="manager", context_id="CTX-42")
    content["constraints"].append("mutated after create")  # caller mutation must not leak in
    v2 = await store.create("P1", {"goal": "chat v2"}, author="planner", context_id="CTX-42",
                            change_summary="new goal")
    assert (v1, v2) == (ContextRef(context_id="CTX-42", version=1), ContextRef(context_id="CTX-42", version=2))
    s1, s2 = await store.get(v1), await store.get(v2)
    assert s1.content == {"goal": "chat", "constraints": ["stdlib"]}
    assert (s2.parent_version, s2.author, s2.change_summary) == (1, "planner", "new goal")
    s1.content["goal"] = "edited copy"  # returned snapshot is a copy
    assert (await store.get(v1)).content["goal"] == "chat"
    assert len(await store.history("CTX-42")) == 2


async def test_is_stale_and_latest() -> None:
    store = InMemoryContextStore()
    v1 = await store.create("P1", {"a": 1}, author="m")
    assert not await store.is_stale(v1)
    v2 = await store.create("P1", {"a": 2}, author="m", context_id=v1.context_id)
    assert await store.is_stale(v1) and not await store.is_stale(v2)
    assert await store.latest(v1.context_id) == v2


async def test_hash_is_canonical() -> None:
    assert content_sha256({"a": 1, "b": 2}) == content_sha256({"b": 2, "a": 1})
    assert content_sha256({"a": 1}) != content_sha256({"a": 2})


async def test_missing_and_cross_project() -> None:
    store = InMemoryContextStore()
    with pytest.raises(ContextNotFound) as err:
        await store.get(ContextRef(context_id="CTX-x", version=1))
    assert err.value.code == ErrorCode.MISSING_CONTEXT
    with pytest.raises(ContextNotFound):
        await store.latest("CTX-x")
    ref = await store.create("P1", {}, author="m")
    with pytest.raises(ContextNotFound):
        await store.get(ContextRef(context_id=ref.context_id, version=2))
    with pytest.raises(AuthorizationError):
        await store.create("P2", {}, author="m", context_id=ref.context_id)


async def test_non_json_content_rejected() -> None:
    with pytest.raises(TypeError):
        await InMemoryContextStore().create("P1", {"x": object()}, author="m")
