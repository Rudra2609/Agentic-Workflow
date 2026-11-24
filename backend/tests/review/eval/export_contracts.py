"""Copy the real JSON the agents produced in a recorded golden run into ``samples/review/contracts/`` for the cross-
agent contract suite (Sprint 10 item 10.18, ``tests/e2e/contracts``):

    uv run python -m tests.review.eval.export_contracts [data/demo_final_artifacts]

Per producer contract the newest artifact of the run (a coding project for code / tests / docs / review, the report
project for research / verification), plus the workspace tarball the change set points at and the research report
the verification report checked. Artifacts hold no keys (the gateway never writes one into a result)."""

import asyncio
import json
import sys
from pathlib import Path

from hmap.services.artifact.local import LocalFSArtifactStore

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "samples" / "review" / "contracts"
TYPES = ("requirement-set", "task-graph", "research-report", "verification-report", "code-change-set",
         "test-report", "doc-bundle", "review-report")


async def export(root: Path) -> dict[str, str]:
    store = LocalFSArtifactStore(root)
    OUT.mkdir(parents=True, exist_ok=True)
    found: dict[str, str] = {}
    projects = sorted(p.name for p in root.iterdir() if p.is_dir())
    for pid in projects:
        refs = await store.list(pid)
        for typ in TYPES:
            if typ in found:
                continue
            cands = [r for r in refs if r.artifact_type == typ]
            if not cands:
                continue
            cands.sort(key=lambda r: (r.created_at, r.version), reverse=True)
            ref, data = cands[0], await store.get(cands[0], project_id=pid)
            if typ == "code-change-set":      # one that changed files (a no-model attempt may change none)
                for r in cands:
                    raw = await store.get(r, project_id=pid)
                    if json.loads(raw).get("files_changed"):
                        ref, data = r, raw
                        break
            (OUT / f"{typ}.json").write_text(json.dumps(json.loads(data), indent=2) + "\n", encoding="utf-8")
            found[typ] = f"{pid}/{ref.artifact_id}"
            if typ == "code-change-set":
                ws = json.loads(data)["workspace_ref"]
                wref = next(r for r in refs if r.artifact_id == ws["artifact_id"] and r.version == ws["version"])
                (OUT / "workspace.tar.gz").write_bytes(await store.get(wref, project_id=pid))
            if typ == "verification-report":
                rr = json.loads(data).get("research_report_ref")
                if rr:
                    rref = next(r for r in refs if r.artifact_id == rr["artifact_id"])
                    raw = await store.get(rref, project_id=pid)
                    (OUT / "research-report.json").write_text(json.dumps(json.loads(raw), indent=2) + "\n",
                                                              encoding="utf-8")
                    found["research-report"] = f"{pid}/{rref.artifact_id}"
    (OUT / "SOURCE.json").write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
    return found


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "demo_final_artifacts"
    print(json.dumps(asyncio.run(export(root)), indent=2))
