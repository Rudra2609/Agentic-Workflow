"""Per-task workspace with a path jail (Sprint 7 item 7.1, ported from ``samples/coding/workspace.py``).

Every path the agent gives is resolved (``..`` and symlinks followed) and must stay inside the workspace; absolute
paths, NUL bytes and anything resolving outside are refused and audited. Workspaces travel between tasks as
**deterministic gzip tarballs** (sorted, mtime 0, no owners: the same tree gives the same bytes) and are unpacked
with the same care (no absolute names, no ``..``, regular files and folders only, size and count caps). Diffs are
plain ``difflib`` unified diffs (no git), and :func:`merge3` re-applies a task's change on a moved project head
(plan D2).

Workspaces live outside the project folder (plan D4): ``HMAP_CODING_WORK_DIR`` or ``<tmp>/hmap-coding``.
"""

import difflib
import gzip
import io
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from hmap.core.config import REPO_ROOT, Settings
from hmap.core.tracing import get_logger

log = get_logger("hmap.coding.workspace")

MAX_FILES = 500
MAX_TOTAL_BYTES = 5 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
SKIP_DIRS = frozenset({"__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache", ".ruff_cache",
                       ".mypy_cache", ".tmp", ".idea", ".vscode"})
SKIP_FILES = frozenset({".DS_Store"})


class JailError(Exception):
    """A path or command the agent may not use. The message is written for the model to act on."""


class WorkspaceTooLarge(ValueError):
    """A tree or tarball over the size / file-count caps."""


def skipped(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return (any(p in SKIP_DIRS for p in parts[:-1]) or name in SKIP_FILES or name.endswith((".pyc", ".pyo"))
            or name == ".env" or name.startswith(".env."))


@dataclass
class Workspace:
    root: Path
    audit: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve(strict=True)

    # --- the jail ------------------------------------------------------------------------------------------------
    def path(self, rel: str) -> Path:
        if not rel or "\0" in rel:
            raise self.deny("path", repr(rel), "empty path or NUL byte")
        rel = rel.strip()
        if rel.startswith(("/", "\\", "~")) or Path(rel).is_absolute() or (len(rel) > 1 and rel[1] == ":"):
            raise self.deny("path", rel, "absolute paths are not allowed; use a path inside the workspace")
        resolved = (self.root / rel).resolve()  # follows .. and every symlink that exists
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise self.deny("path", rel, "resolves outside the workspace (.. or a symlink)")
        return resolved

    def rel(self, rel: str) -> str:
        """The normalised workspace-relative form of ``rel`` (after the jail check)."""
        p = self.path(rel)
        return "." if p == self.root else p.relative_to(self.root).as_posix()

    def deny(self, kind: str, what: str, reason: str) -> JailError:
        self.audit.append(f"{kind} denied: {what}: {reason}")
        log.warning("coding.denied", kind=kind, what=what[:200], reason=reason)
        return JailError(f"{what}: {reason}")

    # --- files ---------------------------------------------------------------------------------------------------
    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    def is_file(self, rel: str) -> bool:
        return self.path(rel).is_file()

    def read(self, rel: str) -> str:
        p = self.path(rel)
        if not p.is_file():
            raise FileNotFoundError(f"{rel} does not exist")
        if p.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceTooLarge(f"{rel} is larger than {MAX_FILE_BYTES // 1024} KB")
        data = p.read_bytes()
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"{rel} is not a UTF-8 text file") from None

    def write(self, rel: str, text: str) -> None:
        if skipped(self.rel(rel)):
            raise self.deny("path", rel, "this file or folder is not part of a workspace (.env, caches, .git)")
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceTooLarge(f"{rel}: a file may hold at most {MAX_FILE_BYTES // 1024} KB")
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self.path(rel)  # re-check after creating folders (a folder could be a symlink)
        target.write_text(text, encoding="utf-8")

    def write_tool_file(self, name: str, text: str) -> str:
        """A helper script of the agent's own under ``.tmp/`` (never packed, never shown as a change)."""
        rel = f".tmp/{name}"
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path(rel).write_text(text, encoding="utf-8")
        return rel

    def delete(self, rel: str) -> None:
        p = self.path(rel)
        if p.is_file():
            p.unlink()

    def files(self, suffix: str = "") -> list[str]:
        out = []
        for p in self.root.rglob(f"*{suffix}"):
            if p.is_symlink() or not p.is_file():
                continue
            rel = p.relative_to(self.root).as_posix()
            if not skipped(rel):
                out.append(rel)
        return sorted(out)

    def snapshot(self) -> dict[str, str]:
        """``{path: text}`` of every text file (binary files are left out of prompts and diffs)."""
        out: dict[str, str] = {}
        for rel in self.files():
            try:
                out[rel] = self.read(rel)
            except (ValueError, WorkspaceTooLarge):
                continue
        return out

    def restore(self, files: dict[str, str]) -> None:
        """Make the text files exactly ``files`` (used to roll a failed merge back)."""
        current = set(self.files())
        for rel in current - set(files):
            self.delete(rel)
        for rel, text in files.items():
            self.write(rel, text)


# ----------------------------------------------------------------------------------------------- work folders


def work_root(settings: Settings) -> Path:
    """Where per-task workspaces live: never inside the project folder (``.env`` is there)."""
    root = Path(settings.coding_work_dir) if settings.coding_work_dir else Path(tempfile.gettempdir()) / "hmap-coding"
    root = root.expanduser().resolve()
    if root == REPO_ROOT or root.is_relative_to(REPO_ROOT):
        log.warning("coding work dir inside the project folder; using the temp folder instead", path=str(root))
        root = (Path(tempfile.gettempdir()) / "hmap-coding").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)[:80] or "x"


def new_workspace(settings: Settings, project_id: str, task_id: str, execution_id: str) -> Workspace:
    folder = work_root(settings) / safe_name(project_id) / safe_name(task_id) / safe_name(execution_id)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    return Workspace(folder)


def remove_workspace(ws: Workspace, settings: Settings) -> None:
    if not settings.coding_keep_work:
        shutil.rmtree(ws.root, ignore_errors=True)


# --------------------------------------------------------------------------------------------------- tarballs


def pack(ws: Workspace) -> bytes:
    """Deterministic ``.tar.gz`` of the workspace (same tree → same bytes)."""
    files = ws.files()
    if len(files) > MAX_FILES:
        raise WorkspaceTooLarge(f"workspace has {len(files)} files (max {MAX_FILES})")
    buf = io.BytesIO()
    total = 0
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in files:
            data = ws.path(rel).read_bytes()
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise WorkspaceTooLarge(f"workspace is larger than {MAX_TOTAL_BYTES // (1024 * 1024)} MB")
            info = tarfile.TarInfo(rel)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(buf.getvalue())
    return out.getvalue()


def unpack(data: bytes, ws: Workspace) -> list[str]:
    """Extract a workspace tarball into ``ws`` safely; returns the files written."""
    if len(data) > MAX_TOTAL_BYTES:
        raise WorkspaceTooLarge("workspace tarball is too large")
    written: list[str] = []
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        members = tar.getmembers()
        if len(members) > MAX_FILES * 2:
            raise WorkspaceTooLarge(f"tarball has {len(members)} entries")
        for m in members:
            if m.isdir():
                continue
            if not m.isfile():
                raise ws.deny("tar", m.name, "only regular files may be in a workspace (no links or devices)")
            name = m.name[2:] if m.name.startswith("./") else m.name
            rel = ws.rel(name)            # refuses absolute names, .. and NUL
            if skipped(rel):
                continue
            total += m.size
            if m.size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise WorkspaceTooLarge(f"{rel}: workspace content over the size caps")
            f = tar.extractfile(m)
            if f is None:
                continue
            target = ws.path(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            ws.path(rel)
            target.write_bytes(f.read())
            written.append(rel)
            if len(written) > MAX_FILES:
                raise WorkspaceTooLarge(f"tarball has more than {MAX_FILES} files")
    return sorted(written)


def files_from_tar(data: bytes) -> dict[str, str]:
    """Text files of a workspace tarball, read in memory (the API's file viewer; no extraction)."""
    out: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for m in tar.getmembers():
            if not m.isfile() or m.size > MAX_FILE_BYTES or skipped(m.name):
                continue
            name = m.name[2:] if m.name.startswith("./") else m.name
            if name.startswith("/") or ".." in name.split("/"):
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            try:
                out[name] = f.read().decode("utf-8")
            except UnicodeDecodeError:
                continue
    return dict(sorted(out.items()))


# ------------------------------------------------------------------------------------------------ diff / merge


def unified_diff(before: dict[str, str], after: dict[str, str]) -> str:
    chunks: list[str] = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        a = (old or "").splitlines(keepends=True)
        b = (new or "").splitlines(keepends=True)
        for lines in (a, b):
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n\\ No newline at end of file\n"
        chunks.extend(difflib.unified_diff(a, b, fromfile="/dev/null" if old is None else f"a/{path}",
                                           tofile="/dev/null" if new is None else f"b/{path}", n=3))
    return "".join(chunks)


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def merge3(base: str, ours: str, theirs: str) -> str | None:
    """Line-based three-way merge: ``ours`` and ``theirs`` both changed ``base``. Non-overlapping changes are both
    kept; overlapping, different changes → ``None`` (a conflict)."""
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    b, o, t = base.splitlines(keepends=True), ours.splitlines(keepends=True), theirs.splitlines(keepends=True)

    def hunks(new: list[str]) -> list[tuple[int, int, list[str]]]:
        sm = difflib.SequenceMatcher(None, b, new, autojunk=False)
        return [(i1, i2, new[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]

    out: list[str] = []
    pos = 0
    prev: tuple[int, int, list[str]] | None = None
    for h in sorted(hunks(o) + hunks(t), key=lambda h: (h[0], h[1])):
        i1, i2, lines = h
        # overlapping ranges, or two insertions at the same line, are a conflict unless both made the same change
        if prev is not None and (i1 < pos or (i1 == prev[0] == pos)):
            if h == prev:
                continue
            return None
        out.extend(b[pos:i1])
        out.extend(lines)
        pos, prev = i2, h
    out.extend(b[pos:])
    return "".join(out)


def rebase(base: dict[str, str], ours: dict[str, str], head: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Re-apply the change ``base → ours`` on ``head`` (the project head moved meanwhile). Returns the merged tree
    and the files that conflict (an empty list = clean)."""
    out = dict(head)
    conflicts: list[str] = []
    for path in changed_files(base, ours):
        b, o, h = base.get(path), ours.get(path), head.get(path)
        if o is None:                                  # we deleted it
            if h == b:
                out.pop(path, None)
            elif h is not None:
                conflicts.append(path)
            continue
        if h is None:
            if b is None:                              # we created it, head has no such file
                out[path] = o
            else:                                      # head deleted what we changed
                conflicts.append(path)
            continue
        merged = merge3(b or "", o, h)
        if merged is None:
            conflicts.append(path)
        else:
            out[path] = merged
    return out, conflicts
