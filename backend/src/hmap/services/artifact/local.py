"""``LocalFSArtifactStore``: write-once files under ``HMAP_ARTIFACT_ROOT`` (Sprint 1 item 1.11, research §15).

Layout (one directory per version; the directory name claims the version number atomically)::

    <root>/<project_id>/<artifact_id>/v<version>/<sha256>      the bytes (read-only, 0o444)
    <root>/<project_id>/<artifact_id>/v<version>/meta.json     the ArtifactRef as JSON (read-only, 0o444)

Each file is written to a temp file in the same directory, fsynced, then linked into place with ``os.link`` (atomic
and refuses an existing path; falls back to exists-check + rename on filesystems without hard links). A version
directory without ``meta.json`` is the leftover of a crashed write and is ignored. In Phase B the metadata moves to
the Postgres ``artifacts`` table; the byte layout stays. Blocking IO runs in ``asyncio.to_thread``.
"""

import asyncio
import builtins
import contextlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

from hmap.core.contracts import ArtifactRef
from hmap.core.errors import ArtifactConflict, ArtifactIntegrityError
from hmap.core.ids import new_artifact_id
from hmap.services.artifact.memory import ArtifactNotFound, check_id, check_scope, make_ref, verify

META_FILE = "meta.json"
READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH  # 0o444


def write_once(path: Path, data: bytes) -> None:
    """Atomically create ``path`` with ``data`` and make it read-only. Raises ``ArtifactConflict`` if it exists."""
    if path.exists():
        raise ArtifactConflict(f"refusing to overwrite existing artifact file {path}")
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    tmp: Path | None = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp_name, path)  # atomic; fails if path exists
        except FileExistsError as exc:
            raise ArtifactConflict(f"refusing to overwrite existing artifact file {path}") from exc
        except OSError:  # no hard links on this filesystem
            if path.exists():
                raise ArtifactConflict(f"refusing to overwrite existing artifact file {path}") from None
            os.rename(tmp_name, path)
            tmp = None
        os.chmod(path, READ_ONLY)
    finally:
        if tmp is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()


class LocalFSArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ ArtifactStore

    async def put(self, data: bytes, *, project_id: str, artifact_type: str, media_type: str, created_by: str,
                  artifact_id: str | None = None) -> ArtifactRef:
        check_id("project_id", project_id)
        artifact_id = check_id("artifact_id", artifact_id or new_artifact_id())
        payload = bytes(data)
        async with self._lock:
            return await asyncio.to_thread(self._put_sync, payload, project_id, artifact_id, artifact_type,
                                           media_type, created_by)

    async def get(self, ref: ArtifactRef, *, project_id: str) -> bytes:
        check_scope(ref, project_id)
        check_id("artifact_id", ref.artifact_id)
        return await asyncio.to_thread(self._get_sync, ref, project_id)

    async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None:
        check_id("project_id", project_id)
        check_id("artifact_id", artifact_id)
        return await asyncio.to_thread(self._latest_sync, project_id, artifact_id)

    async def list(self, project_id: str) -> list[ArtifactRef]:
        check_id("project_id", project_id)
        return await asyncio.to_thread(self._list_sync, project_id)

    # ------------------------------------------------------------------ paths

    async def delete_project(self, project_id: str) -> int:
        check_id("project_id", project_id)                   # no path tricks: ids are [A-Za-z0-9_-] only
        async with self._lock:
            return await asyncio.to_thread(self._delete_project_sync, project_id)

    def _delete_project_sync(self, project_id: str) -> int:
        proj = (self.root / project_id).resolve()
        if proj.parent != self.root.resolve() or not proj.is_dir():
            return 0
        removed = sum(1 for p in proj.glob(f"*/v*/{META_FILE}"))

        def make_writable(func, path, _exc):  # type: ignore[no-untyped-def]
            os.chmod(path, stat.S_IRWXU)
            func(path)

        for path in proj.rglob("*"):                         # files are 0o444 by design; unlock them for removal
            with contextlib.suppress(OSError):
                os.chmod(path, stat.S_IRWXU)
        shutil.rmtree(proj, onerror=make_writable)
        return removed

    def version_dir(self, project_id: str, artifact_id: str, version: int) -> Path:
        return self.root / project_id / artifact_id / f"v{version}"

    def path_for(self, ref: ArtifactRef) -> Path:
        """Where the bytes of ``ref`` live (scope = ``ref.access_scope``)."""
        return self.version_dir(ref.access_scope, ref.artifact_id, ref.version) / ref.sha256

    # ------------------------------------------------------------------ sync helpers (run in a thread)

    def _put_sync(self, data: bytes, project_id: str, artifact_id: str, artifact_type: str, media_type: str,
                  created_by: str) -> ArtifactRef:
        art_dir = self.root / project_id / artifact_id
        art_dir.mkdir(parents=True, exist_ok=True)
        prev = self._latest_sync(project_id, artifact_id)
        version = max([*self._version_numbers(art_dir), 0]) + 1
        while True:  # claim the version directory; another process may race us
            try:
                (art_dir / f"v{version}").mkdir()
                break
            except FileExistsError:
                version += 1
        ref = make_ref(data, scheme="file", project_id=project_id, artifact_id=artifact_id, version=version,
                       artifact_type=artifact_type, media_type=media_type, created_by=created_by,
                       supersedes=prev.version if prev else None)
        vdir = art_dir / f"v{version}"
        write_once(vdir / ref.sha256, data)
        write_once(vdir / META_FILE, ref.model_dump_json(indent=2).encode())  # meta last: marks the version done
        return ref

    def _read_meta(self, project_id: str, artifact_id: str, version: int) -> ArtifactRef | None:
        meta = self.version_dir(project_id, artifact_id, version) / META_FILE
        try:
            raw = meta.read_bytes()
        except FileNotFoundError:
            return None
        ref = ArtifactRef.model_validate_json(raw)
        if (ref.artifact_id, ref.version, ref.access_scope) != (artifact_id, version, project_id):
            raise ArtifactIntegrityError(f"metadata at {meta} does not match its location")
        return ref

    def _get_sync(self, ref: ArtifactRef, project_id: str) -> bytes:
        stored = self._read_meta(project_id, ref.artifact_id, ref.version)
        if stored is None:
            raise ArtifactNotFound(f"artifact {ref.artifact_id}@{ref.version} not found in project {project_id}")
        blob = self.version_dir(project_id, ref.artifact_id, ref.version) / stored.sha256
        try:
            data = blob.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactIntegrityError(f"artifact {ref.artifact_id}@{ref.version}: bytes missing") from exc
        return verify(data, ref, stored)

    @staticmethod
    def _version_numbers(art_dir: Path) -> builtins.list[int]:
        if not art_dir.is_dir():
            return []
        out = []
        for p in art_dir.iterdir():
            if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit():
                out.append(int(p.name[1:]))
        return out

    def _latest_sync(self, project_id: str, artifact_id: str) -> ArtifactRef | None:
        for version in sorted(self._version_numbers(self.root / project_id / artifact_id), reverse=True):
            ref = self._read_meta(project_id, artifact_id, version)
            if ref is not None:
                return ref
        return None

    def _list_sync(self, project_id: str) -> builtins.list[ArtifactRef]:
        proj = self.root / project_id
        refs: builtins.list[ArtifactRef] = []
        if proj.is_dir():
            for art_dir in proj.iterdir():
                for version in self._version_numbers(art_dir):
                    ref = self._read_meta(project_id, art_dir.name, version)
                    if ref is not None:
                        refs.append(ref)
        return sorted(refs, key=lambda r: (r.created_at, r.artifact_id, r.version))
