"""Item 7.1: the path jail, tarballs (incl. tar-slip), diffs and the three-way merge of the project head."""

import io
import tarfile
from pathlib import Path

import pytest

from hmap.agents.coding import workspace as w
from hmap.agents.coding.workspace import JailError, Workspace, WorkspaceTooLarge
from hmap.core.config import REPO_ROOT, Settings


@pytest.fixture
def jailed(tmp_path: Path) -> tuple[Workspace, Path]:
    root, outside = tmp_path / "ws", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("outside data")
    (root / "app.py").write_text("x = 1\n")
    (root / "link_out").symlink_to(outside, target_is_directory=True)
    (root / "hosts_link").symlink_to("/etc/hosts")
    return Workspace(root), outside


@pytest.mark.parametrize("rel", ["../outside/secret.txt", "sub/../../outside/secret.txt", "/etc/passwd",
                                 "hosts_link", "app.py\0.txt", "~/.ssh/id_rsa", ""])
def test_reads_outside_the_workspace_are_refused_and_audited(jailed: tuple[Workspace, Path], rel: str) -> None:
    ws, _ = jailed
    with pytest.raises(JailError):
        ws.read(rel)
    assert ws.audit and "denied" in ws.audit[-1]


def test_write_through_a_symlinked_folder_is_refused(jailed: tuple[Workspace, Path]) -> None:
    ws, outside = jailed
    with pytest.raises(JailError):
        ws.write("link_out/planted.py", "x = 1\n")
    assert not (outside / "planted.py").exists()


def test_normal_nested_write_and_listing(jailed: tuple[Workspace, Path]) -> None:
    ws, _ = jailed
    ws.write("pkg/new_module.py", "x = 1\n")
    assert ws.read("pkg/new_module.py") == "x = 1\n"
    assert "pkg/new_module.py" in ws.files()
    assert "hosts_link" not in ws.files() and "link_out/secret.txt" not in ws.files()  # symlinks are not files


@pytest.mark.parametrize("rel", [".env", "sub/.env.local", ".git/config", "__pycache__/a.pyc"])
def test_env_files_and_caches_are_never_part_of_a_workspace(ws: Workspace, rel: str) -> None:
    with pytest.raises(JailError):
        ws.write(rel, "KEY=1\n")


def test_work_root_is_never_inside_the_project_folder(tmp_path: Path) -> None:
    inside = Settings.from_env({"HMAP_CODING_WORK_DIR": str(REPO_ROOT / "data" / "coding_work")})
    assert not w.work_root(inside).is_relative_to(REPO_ROOT)
    outside = Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path / "work")})
    assert w.work_root(outside) == (tmp_path / "work").resolve()


def test_new_workspace_is_fresh_and_removed_after_use(settings: Settings) -> None:
    ws = w.new_workspace(settings, "P/1", "T 1", "E1")
    ws.write("a.py", "x = 1\n")
    again = w.new_workspace(settings, "P/1", "T 1", "E1")
    assert again.files() == []                     # a redelivered execution starts clean
    w.remove_workspace(again, settings)
    assert not again.root.exists()


# --------------------------------------------------------------------------------------------------- tarballs


def test_pack_is_deterministic_and_round_trips(ws: Workspace, tmp_path: Path) -> None:
    ws.write("b.py", "b = 2\n")
    ws.write("pkg/a.py", "a = 1\n")
    (ws.root / "__pycache__").mkdir()
    (ws.root / "__pycache__" / "b.cpython-311.pyc").write_bytes(b"\0")
    (ws.root / ".env").write_text("SECRET=1\n")
    data = w.pack(ws)
    assert w.pack(ws) == data
    out = tmp_path / "out"
    out.mkdir()
    assert w.unpack(data, Workspace(out)) == ["b.py", "pkg/a.py"]   # no .env, no caches
    assert w.files_from_tar(data) == {"b.py": "b = 2\n", "pkg/a.py": "a = 1\n"}


def _tar(entries: list[tarfile.TarInfo], payload: bytes = b"x") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for info in entries:
            tar.addfile(info, io.BytesIO(payload) if info.isfile() else None)
    return buf.getvalue()


def _info(name: str, kind: bytes = tarfile.REGTYPE, link: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type, info.linkname, info.size = kind, link, 1 if kind == tarfile.REGTYPE else 0
    return info


@pytest.mark.parametrize("entry", [_info("../escape.py"), _info("/etc/evil.py"), _info("a/../../escape.py"),
                                   _info("link", tarfile.SYMTYPE, "/etc/hosts"),
                                   _info("hard", tarfile.LNKTYPE, "/etc/hosts"), _info("dev", tarfile.CHRTYPE)])
def test_unpack_refuses_tar_slip_links_and_devices(ws: Workspace, tmp_path: Path, entry: tarfile.TarInfo) -> None:
    with pytest.raises(JailError):
        w.unpack(_tar([entry]), ws)
    assert not (tmp_path / "escape.py").exists()


def test_unpack_enforces_the_size_caps(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(w, "MAX_FILES", 3)
    with pytest.raises(WorkspaceTooLarge):
        w.unpack(_tar([_info(f"f{i}.py") for i in range(5)]), ws)
    monkeypatch.setattr(w, "MAX_FILE_BYTES", 10)
    with pytest.raises(WorkspaceTooLarge):
        big = _info("big.py")
        big.size = 50
        w.unpack(_tar([big], b"y" * 50), ws)


def test_pack_refuses_oversized_trees(ws: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    for i in range(4):
        ws.write(f"f{i}.py", "x = 1\n")
    monkeypatch.setattr(w, "MAX_FILES", 3)
    with pytest.raises(WorkspaceTooLarge):
        w.pack(ws)


# ------------------------------------------------------------------------------------------------ diff / merge


def test_unified_diff_covers_create_change_delete() -> None:
    diff = w.unified_diff({"a.py": "x = 1\n", "gone.py": "g = 1\n"}, {"a.py": "x = 2\n", "new.py": "n = 1"})
    assert "--- a/a.py\n+++ b/a.py" in diff and "-x = 1\n+x = 2" in diff
    assert "--- /dev/null\n+++ b/new.py" in diff and "\\ No newline at end of file" in diff
    assert "--- a/gone.py\n+++ /dev/null" in diff
    assert w.changed_files({"a": "1"}, {"a": "1", "b": "2"}) == ["b"]


def test_merge3_keeps_both_sides_or_reports_a_conflict() -> None:
    base = "a\nb\nc\nd\ne\n"
    ours = "a\nB\nc\nd\ne\n"
    theirs = "a\nb\nc\nd\nE\n"
    assert w.merge3(base, ours, theirs) == "a\nB\nc\nd\nE\n"
    assert w.merge3(base, ours, ours) == ours
    assert w.merge3(base, ours, base) == ours
    assert w.merge3(base, "a\nX\nc\nd\ne\n", "a\nY\nc\nd\ne\n") is None
    assert w.merge3("", "x\n", "y\n") is None          # both inserted at the same place


def test_rebase_reapplies_a_change_on_a_moved_head() -> None:
    base = {"server.py": "import socket\n\nrun()\n", "room.py": "r = 1\n"}
    ours = {"server.py": "import socket\nimport threading\n\nrun()\n", "room.py": "r = 1\n", "new.py": "n = 1\n"}
    head = {"server.py": "import socket\n\nrun()\nlog()\n", "room.py": "r = 2\n", "other.py": "o = 1\n"}
    merged, conflicts = w.rebase(base, ours, head)
    assert conflicts == []
    assert merged == {"server.py": "import socket\nimport threading\n\nrun()\nlog()\n", "room.py": "r = 2\n",
                      "other.py": "o = 1\n", "new.py": "n = 1\n"}
    _, conflicts = w.rebase(base, {**base, "room.py": "r = 3\n"}, head)
    assert conflicts == ["room.py"]
