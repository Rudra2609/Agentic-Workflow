"""Markdown + JSON report for a regression check (attach it to the commit / handoff)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hmaptools.ownership import Ownership, OwnershipReport
from hmaptools.regression import ORDER, Classified, summarize, verdict
from hmaptools.tree import TreeDiff

EXPLAIN = {
    "NEW_FAILURE": "passed before, fails now — caused by this change",
    "NEW_TEST_FAILING": "new test that fails — caused by this change",
    "NEWLY_RUN_FAILING": "was skipped before (e.g. infra missing), fails now — check it",
    "FLAKY": "inconsistent across re-runs — not attributable to either side",
    "PRE_EXISTING": "already failing before this change — NOT caused by it",
    "NEWLY_SKIPPED": "passed before, skipped now — check why",
    "REMOVED": "existed before, gone now — was a test deleted?",
    "FIXED": "failed before, passes now",
}


def _owner_label(own: Ownership | None, path: str) -> str:
    if own is None:
        return "?"
    m = own.owner(path)
    return f"M{m}" if m else "unowned"


def likely_cause(items: list[Classified], tree_diff: TreeDiff, own: Ownership | None,
                 member: int | None) -> list[str]:
    """Point at the changed files that most likely broke the tests (heuristic, never a verdict by itself).

    Non-test files whose owner also owns a broken test come first. With ``member`` (the person running the check),
    say explicitly when none of that member's changes can be the cause: they touched no non-test file and none of
    the broken tests is theirs.
    """
    broken = [i for i in items if i.category in ("NEW_FAILURE", "NEW_TEST_FAILING")]
    if not broken:
        return []

    def owner(path: str) -> int | None:
        return own.owner(path) if own else None

    def test_path(i: Classified) -> str:
        return "backend/" + i.nodeid.split("::")[0]

    test_owners = {owner(test_path(i)) for i in broken}
    source = [p for p in tree_diff.changed if "/tests/" not in f"/{p}"]
    ranked = sorted(source, key=lambda p: (owner(p) not in test_owners, p))
    owners = ", ".join(sorted({_owner_label(own, test_path(i)) for i in broken}))
    lines = ["", "## Likely cause (heuristic)", "",
             f"Broken tests belong to {owners}. Changed non-test files, most suspicious first:", ""]
    lines += [f"- `{p}` ({_owner_label(own, p)})" for p in ranked[:15]]
    if not ranked:
        lines.append("- none — only test files changed; look at the failing tests themselves")
    if member is not None:
        mine = [p for p in source if owner(p) == member]
        my_tests = [i.nodeid for i in broken if owner(test_path(i)) == member]
        if not mine and not my_tests:
            others = sorted({_owner_label(own, p) for p in source}) or ["test-only changes"]
            lines += ["", f"**Not caused by Member {member}:** Member {member} changed no non-test file and none of "
                      f"the broken tests is theirs. Look at the changes by {', '.join(others)}."]
        else:
            lines += ["", f"Member {member}'s own changes may be involved: "
                      + ", ".join(f"`{x}`" for x in (mine + my_tests)[:10])]
    return lines


def render(*, base_label: str, items: list[Classified], tree_diff: TreeDiff, own: Ownership | None,
           own_report: OwnershipReport | None, env: dict[str, str], timings: dict[str, float],
           out_dir: Path) -> tuple[Path, Path]:
    ok, why = verdict(items)
    counts = summarize(items)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    lines = [f"# Regression check — {'PASS' if ok else 'FAIL'}: {why}", "",
             f"- Base: `{base_label}`", f"- When: {now}",
             f"- Environment: Python {env['python']}, {env['platform']}, {env['uv']}",
             f"- Test time: base {timings.get('base', 0):.0f}s, current {timings.get('current', 0):.0f}s", "",
             "| Category | Count | Meaning |", "|---|---|---|"]
    for cat in ORDER:
        if cat != "PASSING" and counts[cat]:
            lines.append(f"| **{cat}** | {counts[cat]} | {EXPLAIN[cat]} |")
    lines.append(f"| PASSING | {counts['PASSING']} | unchanged and green |")
    lines += likely_cause(items, tree_diff, own, own_report.member if own_report is not None else None)
    for cat in [c for c in ORDER if c != "PASSING"]:
        rows = [i for i in items if i.category == cat]
        if not rows:
            continue
        lines += ["", f"## {cat} ({len(rows)})", "",
                  "| Test | Test owner | Base | Current | Re-runs (base / current) |", "|---|---|---|---|---|"]
        for i in rows:
            test_file = "backend/" + i.nodeid.split("::")[0]
            reruns = f"{','.join(i.reruns_base) or '-'} / {','.join(i.reruns_current) or '-'}"
            lines.append(f"| `{i.nodeid}` | {_owner_label(own, test_file)} | {i.base or '—'} | {i.current or '—'} "
                         f"| {reruns} |")
        if cat in ("NEW_FAILURE", "NEW_TEST_FAILING"):
            ids = " ".join(f"'{i.nodeid}'" for i in rows[:5])
            lines += ["", f"Reproduce: `cd backend && uv run pytest {ids}`"]
    lines += ["", f"## Files changed vs base ({len(tree_diff.changed)})", ""]
    if tree_diff.changed:
        by_owner: dict[str, list[str]] = {}
        for p in tree_diff.changed:
            by_owner.setdefault(_owner_label(own, p), []).append(p)
        for owner_key in sorted(by_owner):
            lines.append(f"- **{owner_key}**: " + ", ".join(f"`{p}`" for p in by_owner[owner_key][:40])
                         + (" …" if len(by_owner[owner_key]) > 40 else ""))
    else:
        lines.append("- none")
    if own_report is not None:
        lines += ["", f"## Ownership (as Member {own_report.member})", ""]
        if own_report.errors:
            lines += [f"- ❌ `{p}` — {kind} (owner: {'M' + str(o) if o else 'none'})"
                      for p, kind, o in own_report.errors]
        if own_report.needs_signoff:
            lines += [f"- ⚠️ `{p}` — {kind}: needs Member 1 sign-off" for p, kind, _ in own_report.needs_signoff]
        if not own_report.errors and not own_report.needs_signoff:
            lines.append("- ✅ only own paths changed")
    md = "\n".join(lines) + "\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"regression-{now}.md"
    json_path = out_dir / f"regression-{now}.json"
    md_path.write_text(md)
    payload: dict[str, Any] = {"pass": ok, "verdict": why, "base": base_label, "counts": counts, "env": env,
                               "timings": timings, "changed_files": tree_diff.to_dict(),
                               "tests": [i.__dict__ for i in items if i.category != "PASSING"]}
    if own_report is not None:
        payload["ownership"] = {"member": own_report.member, "rows": own_report.rows}
    json_path.write_text(json.dumps(payload, indent=1))
    return md_path, json_path
