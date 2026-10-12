"""The team's pre-commit tooling must itself be trustworthy: classification, ownership and tree diffs."""

from pathlib import Path

import pytest
from hmaptools import ownership, regression, report, tree

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(("base", "current", "expected"), [
    ("passed", "failed", "NEW_FAILURE"),
    ("passed", "error", "NEW_FAILURE"),
    (None, "failed", "NEW_TEST_FAILING"),
    ("failed", "failed", "PRE_EXISTING"),
    ("error", "failed", "PRE_EXISTING"),
    ("skipped", "failed", "NEWLY_RUN_FAILING"),
    ("failed", "passed", "FIXED"),
    ("passed", "skipped", "NEWLY_SKIPPED"),
    ("passed", None, "REMOVED"),
    ("passed", "passed", "PASSING"),
    ("skipped", "skipped", "PASSING"),
])
def test_classification_table(base, current, expected) -> None:
    b = {} if base is None else {"t": base}
    c = {} if current is None else {"t": current}
    [item] = regression.classify(b, c)
    assert item.category == expected


def test_only_changes_caused_by_you_block() -> None:
    items = regression.classify({"a": "failed", "b": "passed"}, {"a": "failed", "b": "passed"})
    assert regression.verdict(items)[0]                      # pre-existing failure does not block
    items = regression.classify({"a": "passed"}, {"a": "failed"})
    assert not regression.verdict(items)[0]


@pytest.fixture(scope="module")
def own() -> ownership.Ownership:
    return ownership.Ownership.load(REPO / "ownership.toml")


@pytest.mark.parametrize(("member", "path", "kind"), [
    (3, "backend/src/hmap/agents/planning/agent.py", "own"),
    (3, "frontend/src/features/planning/index.ts", "own"),
    (3, "docs/members/3/research.md", "own"),
    (3, "docs/members/5/core-requests.md", "common"),
    (3, "backend/src/hmap/agents/doc_intel/agent.py", "foreign"),
    (3, "backend/src/hmap/manager/manager.py", "shared"),
    (6, "backend/src/hmap/core/policy.py", "cross_cutting"),
    (1, "frontend/src/app/page.tsx", "own"),
    (1, "frontend/src/features/review/index.ts", "foreign"),
    (2, "some/new/top_level_file.txt", "unowned"),
    (2, "backend/alembic/versions/002_sprint_2_doc_intel.py", "own"),
    (2, "backend/alembic/versions/003_sprint_3_planning.py", "foreign"),
])
def test_ownership_rules(own, member, path, kind) -> None:
    assert own.classify(member, path) == kind


def test_every_member_has_paths_and_plugins_are_distinct(own) -> None:
    assert set(own.members) == set(range(1, 12))
    import tomllib
    data = tomllib.loads((REPO / "ownership.toml").read_text())
    plugins = [v["plugin"] for k, v in data["members"].items() if "plugin" in v]
    assert len(plugins) == len(set(plugins)) == 10


def test_tree_manifest_and_diff(tmp_path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.py").write_text("1")
    (tmp_path / "keep.txt").write_text("k")
    (tmp_path / ".env").write_text("SECRET=1")                 # never part of a manifest
    (tmp_path / ".env.example").write_text("SECRET=")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "big.js").write_text("x")
    base = tree.manifest(tmp_path)
    assert set(base) == {"a/x.py", "keep.txt", ".env.example"}
    (tmp_path / "a" / "x.py").write_text("2")
    (tmp_path / "keep.txt").unlink()
    (tmp_path / "new.md").write_text("n")
    d = tree.diff(base, tree.manifest(tmp_path))
    assert (d.added, d.removed, d.modified) == (["new.md"], ["keep.txt"], ["a/x.py"])
    tree.write_manifest(tmp_path, {"sprint": 1})
    assert "MANIFEST.json" not in tree.manifest(tmp_path)           # a snapshot's own manifest is not content
    assert tree.load_manifest(tmp_path) == tree.manifest(tmp_path)   # reading it back = recomputing


def test_secret_scan_finds_keys_but_not_placeholders(tmp_path) -> None:
    from hmaptools import secrets
    fake_groq = "gsk_" + "A1b2C3d4" * 6                      # built at runtime: this file never contains a key
    fake_google = "AIza" + "Sy" + "x" * 33
    (tmp_path / "config.py").write_text(f'KEY = "{fake_groq}"\nOTHER = "{fake_google}"\n')
    (tmp_path / "README.md").write_text("HMAP_GROQ_API_KEYS=gsk_...,gsk_...\n")   # placeholder: fine
    (tmp_path / ".env").write_text(f"HMAP_GROQ_API_KEYS={fake_groq}\n")            # the allowed place
    found = secrets.scan(tmp_path)
    assert {(f.path, f.kind) for f in found} == {("config.py", "groq_key"), ("config.py", "google_api_key")}
    assert all(fake_groq not in f.preview for f in found)                    # never echo the full key


def test_repo_has_no_secrets() -> None:
    from hmaptools import secrets
    assert secrets.scan(REPO) == []


def _broken(nodeid: str) -> regression.Classified:
    return regression.Classified(nodeid=nodeid, category="NEW_FAILURE", base="passed", current="failed")


def test_likely_cause_clears_a_member_whose_changes_cannot_be_the_cause(own) -> None:
    """Member 2 merged with someone else's core edit: the report must point at the core file and clear Member 2."""
    diff = tree.TreeDiff(added=["backend/tests/doc_intel/test_ids.py"], modified=["backend/src/hmap/core/errors.py"])
    text = "\n".join(report.likely_cause([_broken("tests/core/test_core_utils.py::test_retry_classifier")], diff,
                                         own, member=2))
    assert "`backend/src/hmap/core/errors.py` (M1)" in text
    assert "**Not caused by Member 2:**" in text and "changes by M1" in text


def test_likely_cause_implicates_the_member_own_source_change(own) -> None:
    diff = tree.TreeDiff(modified=["backend/src/hmap/agents/doc_intel/agent.py", "backend/src/hmap/core/ids.py"])
    lines = report.likely_cause([_broken("tests/doc_intel/test_agent.py::test_x")], diff, own, member=2)
    suspects = [ln for ln in lines if ln.startswith("- `")]
    assert suspects[0].startswith("- `backend/src/hmap/agents/doc_intel/agent.py`")   # same owner as the test first
    assert "Not caused" not in "\n".join(lines) and "own changes may be involved" in lines[-1]


def test_likely_cause_is_silent_when_nothing_broke(own) -> None:
    items = regression.classify({"a": "failed"}, {"a": "failed"})                    # pre-existing only
    assert report.likely_cause(items, tree.TreeDiff(modified=["x.py"]), own, member=2) == []
