"""Deleting a project erases its (read-only, write-once) files — and nothing else."""

import pytest

from hmap.core.errors import HmapError
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.services.artifact.memory import InMemoryArtifactStore


@pytest.mark.parametrize("kind", ["local", "memory"])
async def test_delete_project_erases_only_that_project(kind, tmp_path) -> None:
    store = LocalFSArtifactStore(tmp_path / "a") if kind == "local" else InMemoryArtifactStore()
    ref = await store.put(b"v1", project_id="P-1", artifact_type="doc", media_type="text/plain", created_by="t")
    await store.put(b"v2", project_id="P-1", artifact_type="doc", media_type="text/plain", created_by="t",
                    artifact_id=ref.artifact_id)
    keep = await store.put(b"other", project_id="P-2", artifact_type="doc", media_type="text/plain", created_by="t")
    assert await store.delete_project("P-1") == 2
    assert await store.list("P-1") == []
    assert await store.get(keep, project_id="P-2") == b"other"
    assert await store.delete_project("P-1") == 0                    # idempotent
    if kind == "local":
        assert not (tmp_path / "a" / "P-1").exists()


async def test_delete_refuses_path_tricks(tmp_path) -> None:
    store = LocalFSArtifactStore(tmp_path / "a")
    (tmp_path / "precious.txt").write_text("keep me")
    for bad in ("..", "../a", "P-1/../../x", ""):
        with pytest.raises(HmapError):
            await store.delete_project(bad)
    assert (tmp_path / "precious.txt").read_text() == "keep me"
