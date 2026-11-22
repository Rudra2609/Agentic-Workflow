"""Documentation evaluation (Sprint 9 item 9.12) and dogfood (item 9.11).

    cd backend
    uv run python -m tests.docgen.eval.run_eval                              # rules only: seeded + false alarms
    uv run python -m tests.docgen.eval.run_eval --generate                   # + the agent on every repo (replay)
    HMAP_LLM_RECORD_MISSING=docgen uv run python -m tests.docgen.eval.run_eval --generate --free --write  # record
    uv run python -m tests.docgen.eval.run_eval --generate --local-only --name local --mode live     # local model

Repositories: **seen** = the prototype's 3 repos (the rules were written next to them); **unseen** = Member 7's 4
project templates, the Sprint 7 benchmark starter ``b2_broadcast_crash``, the Sprint 8 seeded-suite module, and
**the platform itself** (backend + infra + scripts + Makefile). Sets:

1. **Seeded false claims**: the prototype's 34 sentences (seen) + ``samples/docgen/unseen/seeded.json`` (unseen,
   written after the rules), each appended to a correct README. Detection per claim type.
2. **False alarms**: every hand-written README (seen + unseen, incl. the platform's root README) checked as is;
   flagged claims are listed for labelling (a flag on the platform README can be real drift).
3. **Generated documents** (``--generate``): the real agent (model, refine loop, sandbox examples) per repo.
   Faithfulness (grounded % before the final gate), claims removed, coverage of public symbols, examples run /
   failed, documented endpoints = code endpoints, model calls, seconds. ``--write``: the documents go to
   ``samples/docgen/dogfood/<repo>/`` (the platform's are the start of ``docs/members/9/platform/``).
4. **Model-written free READMEs** (``--free``): the model writes a README from the code alone (no facts, no
   checker), as an ordinary assistant would; the rules flag its claims. Hand labels in
   ``samples/docgen/model_written/labels.json`` turn the flags into precision / recall.

Results: ``samples/docgen/eval_results/<name>.json``.
"""

import argparse
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from hmap.agents.docgen.agent import DocAgent
from hmap.agents.docgen.grounding import rule_claims
from hmap.agents.docgen.inspect import inspect_files, read_tree
from hmap.agents.docgen.model import Accuracy, DocgenTrace, Facts
from hmap.agents.testing.sandbox.local import LocalBackend
from hmap.core.config import Settings
from hmap.core.contracts import TaskAssign
from hmap.core.contracts.capabilities import DOCS_GENERATE
from hmap.core.llm.gateway import Gateway
from hmap.core.runtime.base import AgentContext
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore
from tests.docgen.conftest import tar_of

ROOT = Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "samples" / "docgen"
TEMPLATES = ROOT / "backend" / "src" / "hmap" / "agents" / "coding" / "templates"
SEEN = {n: SAMPLES / "repos" / n for n in ("tcp_chat", "todo_api", "csv_report")}
UNSEEN = {**{f"tpl_{p.name}": p for p in sorted(TEMPLATES.iterdir()) if p.is_dir() and not p.name.startswith("__")},
          "b2_broadcast_crash": ROOT / "samples" / "coding" / "tasks" / "b2_broadcast_crash" / "starter",
          "chatproto": ROOT / "samples" / "testing" / "seeded_failures" / "good"}
PLATFORM_PARTS = ("backend/src", "backend/tests", "backend/pyproject.toml", "backend/alembic", "infra", "scripts",
                  "Makefile", ".env.example", "frontend/package.json", "README.md")


def platform_files() -> dict[str, str]:
    """The platform's code and configuration (read) plus the names of its other files (docs, frontend, samples:
    listed with empty content so path claims about them can be checked; their contents are not facts)."""
    files: dict[str, str] = {".gitignore": (ROOT / ".gitignore").read_text(encoding="utf-8")}
    for part in PLATFORM_PARTS:
        p = ROOT / part
        if p.is_file():
            files[part] = p.read_text(encoding="utf-8")
        elif p.is_dir():
            files.update({f"{part}/{k}": v for k, v in read_tree(p).items()
                          if "/templates/" not in f"/{part}/{k}" and not k.endswith(".json")})
    return files


def platform_listing() -> list[str]:
    """Every other path of the repository, names only (docs, frontend, samples): path claims about them can be
    checked; their contents are not facts."""
    skip = {".git", "node_modules", ".venv", ".next", "__pycache__", "data", "logs", "reports", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", "llm_cache"}
    return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                  if p.is_file() and not skip & set(p.relative_to(ROOT).parts) and p.name != ".env")


def repo_files(name: str) -> dict[str, str]:
    if name == "platform":
        return platform_files()
    path = {**SEEN, **UNSEEN}[name]
    return {k: v for k, v in read_tree(path).items() if k != "template.json"}


def readme(name: str) -> str:
    files = repo_files(name)
    return files.get("README.md", "")


# ------------------------------------------------------------------------------------------- 1 + 2: rules


def seeded() -> dict[str, Any]:
    sets = [("seen", json.loads((SAMPLES / "seeded.json").read_text())),
            ("unseen", json.loads((SAMPLES / "unseen" / "seeded.json").read_text()))]
    out: dict[str, Any] = {}
    for label, seeds in sets:
        by: dict[str, list[int]] = {}
        misses = []
        cache: dict[str, Any] = {}
        for s in seeds:
            facts = cache.setdefault(s["repo"], inspect_files(repo_files(s["repo"]), s["repo"],
                                                              platform_listing() if s["repo"] == "platform" else None))
            doc = readme(s["repo"]).rstrip() + "\n\n" + s["sentence"] + "\n"
            bad = [c for c in rule_claims(doc, facts) if c.verdict == "ungrounded"]
            caught = any(s["expect"] in c.text for c in bad) if s["expect"] else bool(bad)
            row = by.setdefault(s["category"], [0, 0])
            row[0] += caught
            row[1] += 1
            if s["expect"] and not caught:
                misses.append({"id": s["id"], "sentence": s["sentence"], "flagged": [c.text for c in bad]})
        rule_cats = {k: v for k, v in by.items() if k != "BEHAVIOUR"}
        out[label] = {"caught": sum(v[0] for v in rule_cats.values()), "total": sum(v[1] for v in rule_cats.values()),
                      "by_type": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())}, "misses": misses}
    return out


def false_alarms() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in [*SEEN, *UNSEEN, "platform"]:
        text = readme(name)
        if not text:
            continue
        facts = inspect_files(repo_files(name), name, platform_listing() if name == "platform" else None)
        claims = rule_claims(text, facts, "readme")
        flagged = [{"kind": c.kind, "text": c.text, "why": c.why, "line": c.line} for c in claims
                   if c.verdict == "ungrounded"]
        out[name] = {"claims": len([c for c in claims if c.verdict != "unchecked"]), "flagged": flagged}
    return out


# --------------------------------------------------------------------------------------- 3: generated docs


async def generate(name: str, llm: Any, settings: Settings, write: bool) -> dict[str, Any]:
    files = repo_files(name)
    store = InMemoryArtifactStore()
    ws = await store.put(tar_of(files), project_id="EVAL", artifact_type="workspace", media_type="application/gzip",
                         created_by="eval", artifact_id="ws")
    task = TaskAssign(task_id=f"E-{name}", execution_id="X1", capability=DOCS_GENERATE, project_id="EVAL",
                      objective=f"Write the documentation of {name}", acceptance_criteria=["docs exist"],
                      context_refs=[], artifact_refs=[ws], inputs={"repo_name": "hmap" if name == "platform" else name})
    ctx = AgentContext(task=task, agent_id="docgen-eval", llm=llm, artifacts=store, context=InMemoryContextStore(),
                       logger=logging.getLogger("eval"))
    deps: dict[str, Any] = {"backend": LocalBackend(settings)}
    if name == "platform":
        from hmap.api.app import create_app
        deps["openapi"] = create_app().openapi()
        deps["listing"] = platform_listing()
    started = time.monotonic()
    res = await DocAgent(settings, **deps).handle(task, ctx)
    seconds = round(time.monotonic() - started, 1)
    got = {r.artifact_type: r for r in res.artifact_refs}
    acc = Accuracy.model_validate_json(await store.get(got["doc-accuracy"], project_id="EVAL"))
    trace = DocgenTrace.model_validate_json(await store.get(got["docgen-trace"], project_id="EVAL"))
    docs = {}
    for t, name_ in (("doc-readme", "README.md"), ("doc-api", "api.md"), ("doc-architecture", "architecture.md"),
                     ("doc-summaries", "summaries.md"), ("doc-report", "report.md")):
        if t in got:
            raw = (await store.get(got[t], project_id="EVAL")).decode()
            docs[name_] = json.loads(raw)["markdown"] if t == "doc-summaries" else raw
    facts = Facts.model_validate_json(await store.get(got["docgen-facts"], project_id="EVAL"))   # as the agent saw it
    api_eps = {c.text for c in rule_claims(docs.get("api.md", ""), facts) if c.kind == "ENDPOINT"}
    code_eps = {f"{r.method} {r.path}" for r in facts.routes}
    removed = [{"doc": c.doc, "kind": c.kind, "text": c.text, "why": c.why, "sentence": c.sentence[:200]}
               for c in acc.removed]
    if write and name == "platform":                  # item 9.19: the platform's own docs, published after review
        dest = ROOT / "docs" / "members" / "9" / "platform"
        dest.mkdir(parents=True, exist_ok=True)
        note = (f"> Generated from the code by the documentation agent (`run_eval.py --generate --write`, "
                f"{time.strftime('%Y-%m-%d')}), then reviewed by hand: {acc.grounded}/{acc.checked} claims grounded, "
                f"{len(acc.removed)} removed. Regenerate, do not edit.\n\n")
        for fname, target in (("README.md", "README.md"), ("architecture.md", "architecture.md"), ("api.md", "api.md")):
            if fname in docs:
                (dest / target).write_text(note + docs[fname], encoding="utf-8")
    if write:
        out = SAMPLES / "dogfood" / name
        out.mkdir(parents=True, exist_ok=True)
        for fname, text in docs.items():
            (out / fname).write_text(text, encoding="utf-8")
        small = acc.model_copy(update={"claims": [c for c in acc.claims if c.verdict != "grounded"]})
        (out / "accuracy.json").write_text(small.model_dump_json(indent=1), encoding="utf-8")   # counts + the rest
    return {"repo": name, "outcome": res.outcome, "grounded_pct": acc.grounded_pct, "checked": acc.checked,
            "removed": removed, "unverified": acc.unverified, "still_ungrounded": acc.ungrounded,
            "coverage_pct": acc.coverage_pct,
            "examples": {"run": sum(e.ok is not None for e in acc.examples),
                         "failed": [e.code for e in acc.examples if e.ok is False],
                         "checked": sum(e.action == "check" for e in acc.examples)},
            "endpoints_equal": api_eps == code_eps if code_eps else None,
            "endpoints": [len(api_eps), len(code_eps)], "model_calls": trace.model_calls, "tokens": trace.tokens,
            "rounds": trace.rounds, "degraded": trace.degraded, "seconds": seconds,
            "behaviour": [{"text": c.text[:160], "verdict": c.verdict, "evidence": c.evidence[:120]}
                          for c in [*acc.claims, *acc.removed] if c.by == "model"]}


# ---------------------------------------------------------------------------------- 4: free model READMEs


async def free_readme(name: str, llm: Any) -> dict[str, Any]:
    files = {k: v for k, v in repo_files(name).items() if k != "README.md"}
    code = "\n\n".join(f"### {k}\n{v}" for k, v in sorted(files.items()))[:14_000]
    try:
        resp = await llm.generate("reasoner", [
            {"role": "system", "content": "You write README files for software projects. Answer with the Markdown "
                                          "of the README only."},
            {"role": "user", "content": f"Write a complete README.md for this project: what it does, how to install "
                                        f"and run it, configuration, API / usage, tests.\n\n{code}"}],
            max_tokens=2000, temperature=0.0, seed=7)
    except Exception as exc:
        return {"repo": name, "error": type(exc).__name__, "claims": 0, "flagged": []}
    text = re.sub(r"^```(?:markdown|md)?\n|\n```\s*$", "", resp.text.strip())
    facts = inspect_files(repo_files(name), name)
    claims = rule_claims(text, facts, "free")
    out_dir = SAMPLES / "model_written"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.md").write_text(text, encoding="utf-8")
    flagged = [{"kind": c.kind, "text": c.text, "why": c.why, "line": c.line} for c in claims
               if c.verdict == "ungrounded"]
    return {"repo": name, "claims": len([c for c in claims if c.verdict != "unchecked"]), "flagged": flagged}


def label_free(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Precision / recall from hand labels:
    ``labels.json`` = {repo: {"false_claims": [...], "flag_ok": {text: bool}}}"""
    path = SAMPLES / "model_written" / "labels.json"
    if not path.is_file():
        return {"note": "no labels yet"}
    labels = json.loads(path.read_text())
    tp = fp = fn = 0
    for r in results:
        lab = labels.get(r["repo"], {})
        ok = lab.get("flag_ok", {})
        flags = {f["text"] for f in r["flagged"]}
        tp += sum(1 for f in flags if ok.get(f, False))
        fp += sum(1 for f in flags if ok.get(f) is False)
        fn += sum(1 for c in lab.get("false_claims", []) if not any(c in f or f in c for f in flags))
    return {"true_flags": tp, "false_flags": fp, "missed_false_claims": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None}


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {"name": args.name, "mode": args.mode, "seeded": seeded(), "false_alarms": false_alarms()}
    settings = Settings.from_env().model_copy(update={"testing_sandbox": "local", "testing_stage_timeout_s": 60})
    if args.generate or args.free:
        gw = Gateway(settings.model_copy(update={"llm_mode": args.mode})).for_plugin("docgen")
        llm = gw.local_only() if args.local_only else gw
        repos = args.repos or [*SEEN, *UNSEEN, "platform"]
        if args.generate:
            out["generated"] = [await generate(r, llm, settings, args.write) for r in repos]
        if args.free:
            free = [await free_readme(r, llm) for r in repos if r != "platform"]
            out["model_written"] = {"repos": free, "labels": label_free(free)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generate", action="store_true", help="run the real agent on every repository")
    ap.add_argument("--free", action="store_true", help="model-written READMEs without facts (natural errors)")
    ap.add_argument("--write", action="store_true", help="save the generated documents to samples/docgen/dogfood")
    ap.add_argument("--mode", choices=("replay", "live", "record"), default="replay")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--repos", nargs="*")
    ap.add_argument("--name", default="eval")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    result = asyncio.run(evaluate(args))
    dest = SAMPLES / "eval_results" / f"{args.name}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    s = result["seeded"]
    print(f"seeded: seen {s['seen']['caught']}/{s['seen']['total']}, unseen {s['unseen']['caught']}/"
          f"{s['unseen']['total']}; false alarms: "
          + ", ".join(f"{k} {len(v['flagged'])}/{v['claims']}" for k, v in result["false_alarms"].items()))
    for g in result.get("generated", []):
        print(f"  {g['repo']:22s} {g['grounded_pct']:6.1f} % of {g['checked']:4d}  removed {len(g['removed']):2d}  "
              f"coverage {g['coverage_pct']}  examples {g['examples']['run']} run / {len(g['examples']['failed'])} "
              f"failed  endpoints {g['endpoints']}  calls {g['model_calls']}  {g['seconds']} s"
              + ("  DEGRADED" if g["degraded"] else ""))
    if "model_written" in result:
        print("model-written:", result["model_written"]["labels"],
              [(r["repo"], len(r["flagged"]), r["claims"]) for r in result["model_written"]["repos"]])
    print(f"-> {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
