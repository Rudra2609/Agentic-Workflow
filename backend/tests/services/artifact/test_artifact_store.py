"""Same suite for InMemoryArtifactStore and LocalFSArtifactStore (Sprint 1 item 1.11)."""

import asyncio
import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from hmap.core.contracts import ArtifactRef
from hmap.core.errors import ArtifactConflict, ArtifactIntegrityError, AuthorizationError, HmapError
from hmap.services.artifact.base import ArtifactStore
from hmap.services.artifact.local import LocalFSArtifactStore, write_once
from hmap.services.artifact.memory import ArtifactNotFound, InMemoryArtifactStore

P1, P2 = "P-ONE", "P-TWO"


def _tamper_local(store: LocalFSArtifactStore, ref: ArtifactRef) -> None:
    path = store.path_for(ref)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    path.write_bytes(b"tampered!")


def _tamper_memory(store: InMemoryArtifactStore, ref: ArtifactRef) -> None:
    store._tamper(ref, b"tampered!")


@pytest.fixture(params=["memory", "local"])
def store_and_tamper(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[ArtifactStore, Callable[..., None]]:
    if request.param == "memory":
        mem = InMemoryArtifactStore()
        return mem, lambda ref: _tamper_memory(mem, ref)
    local = LocalFSArtifactStore(tmp_path / "artifacts")
    return local, lambda ref: _tamper_local(local, ref)


@pytest.fixture
def store(store_and_tamper: tuple[ArtifactStore, Callable[..., None]]) -> ArtifactStore:
    return store_and_tamper[0]


async def _put(store: ArtifactStore, data: bytes = b'{"a": 1}', *, project: str = P1,
               artifact_id: str | None = None) -> ArtifactRef:
    return await store.put(data, project_id=project, artifact_type="json", media_type="application/json",
                           created_by="tester", artifact_id=artifact_id)


async def test_put_get_roundtrip(store: ArtifactStore) -> None:
    ref = await _put(store, b"hello")
    assert ref.version == 1 and ref.supersedes is None
    assert ref.access_scope == P1 and ref.size_bytes == 5 and len(ref.sha256) == 64
    assert ref.uri.endswith(f"{P1}/{ref.artifact_id}/v1/{ref.sha256}")
    assert await store.get(ref, project_id=P1) == b"hello"


async def test_same_id_creates_next_version_with_supersedes(store: ArtifactStore) -> None:
    v1 = await _put(store, b"one", artifact_id="ART-1")
    v2 = await _put(store, b"two", artifact_id="ART-1")
    v3 = await _put(store, b"three", artifact_id="ART-1")
    assert (v2.version, v2.supersedes) == (2, 1)
    assert (v3.version, v3.supersedes) == (3, 2)
    assert await store.get(v1, project_id=P1) == b"one"  # old versions are immutable and still readable
    assert await store.get(v2, project_id=P1) == b"two"
    latest = await store.latest("ART-1", project_id=P1)
    assert latest is not None and latest.version == 3
    assert await store.latest("ART-nope", project_id=P1) is None


async def test_list_is_project_scoped(store: ArtifactStore) -> None:
    a = await _put(store, b"a", artifact_id="ART-A")
    b = await _put(store, b"b", artifact_id="ART-A")
    await _put(store, b"c", project=P2)
    listed = await store.list(P1)
    assert [(r.artifact_id, r.version) for r in listed] == [(a.artifact_id, 1), (b.artifact_id, 2)]
    assert len(await store.list(P2)) == 1
    assert await store.list("P-EMPTY") == []


async def test_scope_denied(store: ArtifactStore) -> None:
    ref = await _put(store, b"secret")
    with pytest.raises(AuthorizationError):
        await store.get(ref, project_id=P2)
    # a forged ref claiming the other project's scope finds nothing there
    forged = ref.model_copy(update={"access_scope": P2})
    with pytest.raises(ArtifactNotFound):
        await store.get(forged, project_id=P2)


async def test_tamper_detected(store_and_tamper: tuple[ArtifactStore, Callable[..., None]]) -> None:
    store, tamper = store_and_tamper
    ref = await _put(store, b"original")
    tamper(ref)
    with pytest.raises(ArtifactIntegrityError):
        await store.get(ref, project_id=P1)


async def test_ref_with_wrong_hash_rejected(store: ArtifactStore) -> None:
    ref = await _put(store, b"x")
    bad = ref.model_copy(update={"sha256": "f" * 64})
    with pytest.raises(ArtifactIntegrityError):
        await store.get(bad, project_id=P1)


async def test_unknown_version_not_found(store: ArtifactStore) -> None:
    ref = await _put(store, b"x")
    with pytest.raises(ArtifactNotFound):
        await store.get(ref.model_copy(update={"version": 9}), project_id=P1)


async def test_unsafe_ids_rejected(store: ArtifactStore) -> None:
    for bad in ("../etc", "a/b", ".hidden", ""):
        with pytest.raises(HmapError):
            await _put(store, artifact_id=bad or "..")
    with pytest.raises(HmapError):
        await _put(store, project="../escape")


async def test_concurrent_puts_get_distinct_versions(store: ArtifactStore) -> None:
    refs = await asyncio.gather(*(_put(store, str(i).encode(), artifact_id="ART-C") for i in range(8)))
    assert sorted(r.version for r in refs) == list(range(1, 9))


# ---------------------------------------------------------------------- local-only behaviour


async def test_local_layout_read_only_and_meta(tmp_path: Path) -> None:
    store = LocalFSArtifactStore(tmp_path)
    ref = await _put(store, b"data", artifact_id="ART-L")
    blob = tmp_path / P1 / "ART-L" / "v1" / ref.sha256
    meta = blob.parent / "meta.json"
    assert store.path_for(ref) == blob and blob.read_bytes() == b"data"
    assert ArtifactRef.model_validate_json(meta.read_bytes()) == ref
    for p in (blob, meta):
        assert stat.S_IMODE(p.stat().st_mode) & 0o222 == 0, f"{p} is writable"
    assert ref.uri == f"file://{P1}/ART-L/v1/{ref.sha256}"
    assert not [p for p in blob.parent.iterdir() if p.name.startswith(".tmp-")]


async def test_local_overwrite_refused(tmp_path: Path) -> None:
    store = LocalFSArtifactStore(tmp_path)
    ref = await _put(store, b"data")
    with pytest.raises(ArtifactConflict):
        write_once(store.path_for(ref), b"other")
    assert await store.get(ref, project_id=P1) == b"data"


def test_write_once_refuses_existing(tmp_path: Path) -> None:
    target = tmp_path / "f"
    write_once(target, b"1")
    with pytest.raises(ArtifactConflict):
        write_once(target, b"2")
    assert target.read_bytes() == b"1"
    assert [p.name for p in tmp_path.iterdir()] == ["f"]  # temp file cleaned up


async def test_local_survives_restart_and_ignores_crashed_version(tmp_path: Path) -> None:
    store = LocalFSArtifactStore(tmp_path)
    v1 = await _put(store, b"one", artifact_id="ART-R")
    (tmp_path / P1 / "ART-R" / "v2").mkdir()  # leftover of a crash before meta.json was written
    reopened = LocalFSArtifactStore(tmp_path)
    latest = await reopened.latest("ART-R", project_id=P1)
    assert latest == v1
    v3 = await _put(reopened, b"three", artifact_id="ART-R")
    assert (v3.version, v3.supersedes) == (3, 1)
    assert [r.version for r in await reopened.list(P1)] == [1, 3]


async def test_local_missing_bytes_is_integrity_error(tmp_path: Path) -> None:
    store = LocalFSArtifactStore(tmp_path)
    ref = await _put(store, b"x")
    store.path_for(ref).unlink()
    with pytest.raises(ArtifactIntegrityError):
        await store.get(ref, project_id=P1)
