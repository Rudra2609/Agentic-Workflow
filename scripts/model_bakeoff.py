# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "pydantic>=2.7", "pytest>=8"]
# ///
"""Model bake-off: score local Ollama models on small samples of hmap's real work.

Usage (from the repo root):
    uv run scripts/model_bakeoff.py run --models qwen3.5:9b qwen3:8b
    uv run scripts/model_bakeoff.py report
    uv run scripts/model_bakeoff.py gen-data --model qwen3.5:4b --samples 8   # fine-tune trial data

Data lives in samples/model_bakeoff/, results in samples/model_bakeoff/results/.
Every score is computed by code (keyword answer keys, graph checks, hidden pytest suites); no LLM judges.
Generated code runs under macOS sandbox-exec: no internet, writes only inside its own work folder.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "samples" / "model_bakeoff"
RESULTS = DATA / "results"
OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")  # same variable the platform gateway uses
SUITES = ["extraction", "planning", "critique", "verify", "coding"]
WEIGHTS = {"extraction": 0.25, "planning": 0.20, "critique": 0.15, "verify": 0.15, "coding": 0.25}

# ---------------------------------------------------------------- schemas


class Requirement(BaseModel):
    id: str
    text: str
    type: Literal["functional", "non_functional"]
    priority: Literal["must", "should", "could"]
    source_quote: str


class Constraint(BaseModel):
    id: str
    text: str
    kind: Literal["technology", "format", "process", "resource", "other"]


class Deliverable(BaseModel):
    id: str
    name: str
    format: str


class Criterion(BaseModel):
    id: str
    criterion: str
    max_marks: float


class Extraction(BaseModel):
    requirements: list[Requirement]
    constraints: list[Constraint]
    deliverables: list[Deliverable]
    evaluation_criteria: list[Criterion]
    open_questions: list[str]


Capability = Literal["research.run", "verify.claims", "code.implement", "test.run", "docs.generate", "review.final"]


class PlanTask(BaseModel):
    id: str
    title: str
    capability: Capability
    requirement_ids: list[str]
    depends_on: list[str]
    phase: Literal["research", "design", "implement", "test", "document", "review"]


class Plan(BaseModel):
    tasks: list[PlanTask]


class Issue(BaseModel):
    category: Literal["FORMAT", "SCHEMA", "OMISSION", "HALLUCINATION", "FACTUAL", "LOGIC",
                      "REQUIREMENT_VIOLATION", "CONSISTENCY", "STYLE", "SAFETY"]
    severity: Literal["info", "minor", "major", "critical"]
    description: str


class Critique(BaseModel):
    issues: list[Issue]
    verdict: Literal["ok", "needs_revision"]


class Verdict(BaseModel):
    rationale: str
    verdict: Literal["SUPPORTED", "NOT_SUPPORTED", "CONTRADICTED"]


# ---------------------------------------------------------------- prompts

EXTRACT_SYS = (
    "You extract structured information from assignment and project documents. "
    "List every requirement, constraint, deliverable and evaluation criterion that the document states. "
    "Requirements are things the solution must do or satisfy; constraints restrict how it is built or submitted "
    "(technology, length, format, rules); deliverables are the artifacts to hand in; evaluation criteria are the "
    "marking scheme with marks. source_quote must be copied verbatim from the document. Do not invent items. "
    "Use ids R1.., C1.., D1.., E1.."
)
PLAN_SYS = (
    "You are a project planner for a multi-agent system. Break the project into tasks executed by these agents: "
    "research.run (gather information from sources), verify.claims (fact-check research), code.implement (write code), "
    "test.run (run tests against written code), docs.generate (write reports, READMEs, documents), "
    "review.final (final review against the requirements). Rules: every requirement id must appear in at least one "
    "task's requirement_ids; depends_on lists ids of tasks that must finish first; no cycles; finish with one "
    "review.final task that depends on the other work; use code.implement and test.run only if software must be delivered. "
    "Use ids T1, T2, ..."
)
CRITIC_SYS = (
    "You are a strict reviewer. Given a task and the output produced for it, list concrete problems in the output: "
    "missing items, wrong logic, false facts, claims not backed by the given facts, inconsistencies, rule violations. "
    "Describe each problem specifically, naming the exact element that is wrong. "
    "If the output is correct and complete, return verdict ok and no major or critical issues."
)
VERIFY_SYS = (
    "Decide whether the evidence quote supports the claim, judging ONLY from the quote. "
    "SUPPORTED: the quote clearly establishes the claim. CONTRADICTED: the quote states something incompatible with the claim. "
    "NOT_SUPPORTED: the quote is related but does not establish the claim. Give a one-sentence rationale first."
)
CODE_SYS = (
    "You are an expert Python developer. Reply with one complete Python module inside a single ```python code block "
    "and nothing else. Use only the Python standard library."
)


def code_user(task_md: str) -> str:
    return task_md + "\n\nThe module will be saved as solution.py and tested with pytest (tests import from solution)."


# ---------------------------------------------------------------- ollama


def chat(model: str, system: str, user: str, schema: type[BaseModel] | None, *, temperature: float = 0.0,
         seed: int = 42, num_predict: int = 2048) -> dict:
    body = {
        "model": model, "stream": False, "keep_alive": "10m", "think": False,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": temperature, "seed": seed, "num_ctx": 8192, "num_predict": num_predict},
    }
    if schema is not None:
        body["format"] = schema.model_json_schema()
    with httpx.Client(timeout=900) as c:
        r = c.post(f"{OLLAMA}/api/chat", json=body)
        if r.status_code == 400 and "think" in r.text.lower():  # model without a thinking switch
            body.pop("think")
            r = c.post(f"{OLLAMA}/api/chat", json=body)
        r.raise_for_status()
        return r.json()


def chat_messages(model: str, messages: list[dict], *, think: bool, num_predict: int, num_ctx: int,
                  temperature: float = 0.0, seed: int = 42) -> dict:
    """Multi-turn chat (fix loop). With think=True Ollama returns the reasoning in message.thinking."""
    body = {"model": model, "stream": False, "keep_alive": "10m", "think": think, "messages": messages,
            "options": {"temperature": temperature, "seed": seed, "num_ctx": num_ctx, "num_predict": num_predict}}
    with httpx.Client(timeout=3600) as c:
        r = c.post(f"{OLLAMA}/api/chat", json=body)
        r.raise_for_status()
        return r.json()


FIX_PROMPT = ("Your module failed the tests. Here is the pytest output:\n\n{output}\n\n"
              "Fix the problems and reply with the complete corrected module in one ```python code block.")


def cmd_coding_loop(args) -> None:
    """Coding with test feedback: attempt, run hidden tests, on failure send the pytest output back (<= N rounds).
    Records pass/fail after every round, so one run gives pass@1 and pass-after-k-fixes."""
    tag = f"{safe(args.model)}__think{int(args.think)}_fix{args.fix_rounds}"
    out_dir = RESULTS / "_experiments" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "coding.jsonl"
    done = {json.loads(l)["id"] for l in out.read_text().splitlines() if l.strip()} if out.exists() else set()
    num_predict, num_ctx = (8192, 16384) if args.think else (2048, 8192)
    for item in load_items("coding"):
        if item["id"] in done:
            continue
        messages = [{"role": "system", "content": CODE_SYS},
                    {"role": "user", "content": code_user((item["dir"] / "task.md").read_text())}]
        rounds, tokens, think_tokens, seconds = [], 0, 0, 0.0
        for k in range(args.fix_rounds + 1):
            resp = chat_messages(args.model, messages, think=args.think, num_predict=num_predict, num_ctx=num_ctx)
            msg = resp["message"]
            code = extract_code(msg.get("content", ""))
            r = run_tests(item["dir"], code, out_dir / "work" / item["id"] / f"r{k}")
            tokens += resp.get("eval_count", 0)
            think_tokens += len(msg.get("thinking") or "") // 4
            seconds += resp.get("total_duration", 0) / 1e9
            rounds.append({"round": k, "passed": r["passed_all"], "tests_passed": r["tests_passed"],
                           "tests_total": r["tests_total"]})
            if r["passed_all"]:
                break
            pytest_out = (out_dir / "work" / item["id"] / f"r{k}" / "pytest_output.txt").read_text()
            messages += [{"role": "assistant", "content": f"```python\n{code}\n```"},
                         {"role": "user", "content": FIX_PROMPT.format(output=pytest_out[-3000:])}]
        passed_round = next((x["round"] for x in rounds if x["passed"]), None)
        row = {"id": item["id"], "passed_round": passed_round, "rounds": rounds, "out_tokens": tokens,
               "approx_think_tokens": think_tokens, "seconds": round(seconds, 1)}
        with out.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"  {item['id']:24s} passed_round={passed_round} t={seconds:6.1f}s", flush=True)
    rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    summary = {f"pass_after_{k}_fixes": round(sum(1 for r in rows if r["passed_round"] is not None
                                                  and r["passed_round"] <= k) / len(rows), 3)
               for k in range(args.fix_rounds + 1)}
    summary |= {"tasks": len(rows), "avg_seconds_per_task": round(sum(r["seconds"] for r in rows) / len(rows), 1)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def metrics(resp: dict) -> dict:
    ev, evd = resp.get("eval_count", 0), resp.get("eval_duration", 0) or 1
    return {
        "out_tokens": ev, "in_tokens": resp.get("prompt_eval_count", 0),
        "tok_s": round(ev / evd * 1e9, 2),
        "ttft_s": round((resp.get("load_duration", 0) + resp.get("prompt_eval_duration", 0)) / 1e9, 3),
        "load_s": round(resp.get("load_duration", 0) / 1e9, 3),
        "total_s": round(resp.get("total_duration", 0) / 1e9, 3),
    }


def resident_gb(model: str) -> float | None:
    try:
        ps = httpx.get(f"{OLLAMA}/api/ps", timeout=10).json()
    except httpx.HTTPError:
        return None
    for m in ps.get("models", []):
        if m.get("name") == model or m.get("model") == model:
            return round(m.get("size", 0) / 1e9, 2)
    return None


def parse(content: str, schema: type[BaseModel]):
    try:
        return schema.model_validate_json(content), None
    except ValidationError as e:
        return None, str(e)[:500]


# ---------------------------------------------------------------- scoring helpers


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def matches(gold_item: dict, texts: list[str]) -> bool:
    return any(all(k in t for k in alt) for alt in gold_item["any"] for t in texts)


def score_extraction(doc: str, gold: dict, ex: Extraction) -> dict:
    cats = {
        "requirements": [norm(r.text + " " + r.source_quote) for r in ex.requirements],
        "constraints": [norm(c.text) for c in ex.constraints],
        "deliverables": [norm(d.name + " " + d.format) for d in ex.deliverables],
    }
    everything = [t for ts in cats.values() for t in ts] + [norm(e.criterion) for e in ex.evaluation_criteria]
    recall = {}
    for cat, items in (("requirements", gold["requirements"]), ("constraints", gold["constraints"]),
                       ("deliverables", gold["deliverables"])):
        pts = [1.0 if matches(g, cats[cat]) else 0.5 if matches(g, everything) else 0.0 for g in items]
        recall[cat] = sum(pts) / len(pts)
    got_marks = sorted(round(e.max_marks) for e in ex.evaluation_criteria)
    ok_marks = [sorted(gold["marks"])] + [sorted(m) for m in gold.get("alt_marks", [])]
    marks_ok = 1.0 if got_marks in ok_marks else 0.0
    ndoc = norm(doc)
    quotes = [norm(r.source_quote).strip(" \"'\u201c\u201d\u2018\u2019.;,:") for r in ex.requirements
              if r.source_quote.strip()]
    grounded = sum(1 for q in quotes if q and q in ndoc) / len(quotes) if quotes else 0.0
    bloat = len(ex.requirements) > 3 * len(gold["requirements"])
    # things the document explicitly says are NOT required (distractors) must not be extracted
    negated = ("not required", "neither", "optional", "not graded", "ungraded", "no longer", "not needed", "excluded")
    req_like = [t for t in cats["requirements"] + cats["constraints"] if not any(n in t for n in negated)]
    forbidden_hits = [f["id"] for f in gold.get("forbidden", []) if matches(f, req_like)]
    score = (0.5 * recall["requirements"] + 0.15 * recall["constraints"] + 0.15 * recall["deliverables"]
             + 0.1 * marks_ok + 0.1 * grounded) * (0.8 if bloat else 1.0) - 0.15 * len(forbidden_hits)
    return {"score": round(max(0.0, score), 4), "recall": recall, "marks_ok": marks_ok,
            "quote_grounded": round(grounded, 3), "n_requirements": len(ex.requirements), "bloat": bloat,
            "forbidden_hits": forbidden_hits}


def ancestors(tid: str, deps: dict[str, list[str]]) -> set[str]:
    seen, stack = set(), list(deps.get(tid, []))
    while stack:
        t = stack.pop()
        if t not in seen:
            seen.add(t)
            stack.extend(deps.get(t, []))
    return seen


def score_planning(item: dict, plan: Plan) -> dict:
    ids = [t.id for t in plan.tasks]
    deps = {t.id: t.depends_on for t in plan.tasks}
    ids_ok = len(set(ids)) == len(ids) and all(d in deps for ds in deps.values() for d in ds)
    acyclic = ids_ok and all(t not in ancestors(t, deps) for t in ids)
    req_ids = {r["id"] for r in item["requirements"]}
    covered = {r for t in plan.tasks for r in t.requirement_ids} & req_ids
    coverage = len(covered) / len(req_ids)
    reviews = [t.id for t in plan.tasks if t.capability == "review.final"]
    review_ok = bool(reviews) and acyclic and all(
        t in set().union(*(ancestors(r, deps) for r in reviews)) for t in ids if t not in reviews)
    caps = {t.id: t.capability for t in plan.tasks}
    if item["expects_code"]:
        tests = [t for t in ids if caps[t] == "test.run"]
        code_ok = "code.implement" in caps.values() and bool(tests) and acyclic and all(
            any(caps[a] == "code.implement" for a in ancestors(t, deps)) for t in tests)
    else:
        code_ok = not ({"code.implement", "test.run"} & set(caps.values()))
    size_ok = 3 <= len(ids) <= 30
    checks = {"ids_ok": ids_ok, "acyclic": acyclic, "coverage": coverage, "review_sink": review_ok,
              "code_rules": code_ok, "size_ok": size_ok}
    if item.get("must_precede"):  # stated ordering rules: every task covering b needs a task covering a before it
        covers = {t.id: set(t.requirement_ids) for t in plan.tasks}
        ok = 0
        for a, b in item["must_precede"]:
            tb = [t for t in ids if b in covers[t]]
            ok += bool(tb) and acyclic and all(a in covers[t] or any(a in covers[x] for x in ancestors(t, deps))
                                               for t in tb)
        checks["ordering"] = ok / len(item["must_precede"])
    score = sum(float(v) for v in checks.values()) / len(checks)
    return {"score": round(score, 4), **checks, "n_tasks": len(ids)}


def score_critique(item: dict, c: Critique) -> dict:
    if not item["planted"]:
        ok = c.verdict == "ok" and not any(i.severity in ("major", "critical") for i in c.issues)
        return {"score": float(ok), "kind": "clean", "false_alarm": not ok}
    texts = [norm(i.description) for i in c.issues]
    found = c.verdict == "needs_revision" and all(matches(p, texts) for p in item["planted"])
    return {"score": float(found), "kind": "planted", "detected": found}


def score_verify(item: dict, v: Verdict) -> dict:
    return {"score": float(v.verdict == item["label"]), "predicted": v.verdict, "label": item["label"]}


CODE_RE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)


def extract_code(content: str) -> str:
    blocks = CODE_RE.findall(content)
    if blocks:
        return max(blocks, key=len)
    # unclosed fence (e.g. output stopped early): drop the opening fence line instead of failing on it
    return re.sub(r"^\s*```(?:python|py)?[ \t]*\n", "", content).replace("```", "")


def run_tests(task_dir: Path, code: str, workdir: Path) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "solution.py").write_text(code)
    (workdir / "test_solution.py").write_text((task_dir / "test_solution.py").read_text())
    cmd = ["sandbox-exec", "-f", str(DATA / "coding" / "sandbox.sb"), "-D", f"WORKDIR={workdir.resolve()}",
           sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    try:
        p = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=90)
        out, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        out, rc = "TIMEOUT", -1
    last = out.strip().splitlines()[-1] if out.strip() else ""
    n = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|error)", last)}
    total = sum(n.values())
    (workdir / "pytest_output.txt").write_text(out)
    return {"score": float(rc == 0), "passed_all": rc == 0, "tests_passed": n.get("passed", 0),
            "tests_total": total, "test_fraction": round(n.get("passed", 0) / total, 3) if total else 0.0,
            "summary": last[:200]}


# ---------------------------------------------------------------- suites


def load_items(suite: str) -> list[dict]:
    d = DATA / suite
    if suite == "extraction":
        gold = json.loads((d / "gold.json").read_text())
        return [{"id": p.stem, "doc": p.read_text(), "gold": gold[p.stem]} for p in sorted(d.glob("e*.txt"))]
    if suite == "planning":
        return json.loads((d / "inputs.json").read_text())["items"]
    if suite in ("critique", "verify"):
        return json.loads((d / "items.json").read_text())["items"]
    if suite == "coding":
        return [{"id": p.name, "dir": p} for p in sorted(d.glob("c*")) if p.is_dir()]
    raise ValueError(suite)


def run_item(model: str, suite: str, item: dict, mdir: Path) -> dict:
    if suite == "extraction":
        resp = chat(model, EXTRACT_SYS, item["doc"], Extraction)
        obj, err = parse(resp["message"]["content"], Extraction)
        sc = score_extraction(item["doc"], item["gold"], obj) if obj else {"score": 0.0}
    elif suite == "planning":
        user = json.dumps({k: item[k] for k in ("requirements", "constraints", "deliverables", "notes") if k in item},
                          indent=1)
        resp = chat(model, PLAN_SYS, user, Plan)
        obj, err = parse(resp["message"]["content"], Plan)
        sc = score_planning(item, obj) if obj else {"score": 0.0}
    elif suite == "critique":
        user = f"TASK:\n{item['context']}\n\nOUTPUT TO REVIEW:\n{item['artifact']}"
        resp = chat(model, CRITIC_SYS, user, Critique, num_predict=1024)
        obj, err = parse(resp["message"]["content"], Critique)
        sc = score_critique(item, obj) if obj else {"score": 0.0, "kind": "planted" if item["planted"] else "clean"}
    elif suite == "verify":
        user = f"CLAIM: {item['claim']}\nQUOTE: {item['quote']}"
        resp = chat(model, VERIFY_SYS, user, Verdict, num_predict=512)
        obj, err = parse(resp["message"]["content"], Verdict)
        sc = score_verify(item, obj) if obj else {"score": 0.0}
    else:  # coding
        resp = chat(model, CODE_SYS, code_user((item["dir"] / "task.md").read_text()), None)
        err = None
        sc = run_tests(item["dir"], extract_code(resp["message"]["content"]), mdir / "coding_work" / item["id"])
    return {"id": item["id"], "json_valid": err is None, "error": err, **sc, **metrics(resp),
            "output": resp["message"]["content"]}


def safe(model: str) -> str:
    return model.replace(":", "_").replace("/", "_")


def cmd_run(args) -> None:
    suites = SUITES if args.suites == ["all"] else args.suites
    for model in args.models:
        mdir = RESULTS / safe(model)
        mdir.mkdir(parents=True, exist_ok=True)
        print(f"\n### {model}", flush=True)
        t0 = time.time()
        warm = chat(model, "Reply with OK.", "OK?", None, num_predict=8)  # load once; record cold-load time
        meta = {"model": model, "cold_load_s": round(warm.get("load_duration", 0) / 1e9, 2),
                "resident_gb": resident_gb(model)}
        for suite in suites:
            out = mdir / f"{suite}.jsonl"
            done = set()
            if out.exists() and not args.force:
                done = {json.loads(l)["id"] for l in out.read_text().splitlines() if l.strip()}
            elif out.exists():
                out.unlink()
            if args.only and out.exists():  # re-run just these items: drop their old rows
                keep = [l for l in out.read_text().splitlines() if l.strip() and json.loads(l)["id"] not in args.only]
                out.write_text("".join(l + "\n" for l in keep))
                done -= set(args.only)
            for item in load_items(suite):
                if item["id"] in done or (args.only and item["id"] not in args.only):
                    continue
                try:
                    res = run_item(model, suite, item, mdir)
                except httpx.HTTPError as e:
                    res = {"id": item["id"], "score": 0.0, "json_valid": False, "error": f"http: {e}"}
                with out.open("a") as f:
                    f.write(json.dumps(res) + "\n")
                print(f"  {suite:10s} {item['id']:28s} score={res['score']:.2f} "
                      f"tok/s={res.get('tok_s', 0):6.1f} t={res.get('total_s', 0):5.1f}s", flush=True)
            meta["resident_gb"] = meta["resident_gb"] or resident_gb(model)
        meta["wall_s"] = round(time.time() - t0, 1)
        (mdir / "meta.json").write_text(json.dumps(meta, indent=2))
    cmd_report(args)


def cmd_speed(args) -> None:
    """Clean speed pass (run when nothing else is downloading/heavy): median of 3 runs per model."""
    import statistics
    doc = (DATA / "extraction" / "e07_srs_hospital.txt").read_text()
    out = {}
    path = RESULTS / "speed.json"
    if path.exists():
        out = json.loads(path.read_text())
    for model in args.models:
        for m in httpx.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", []):  # one model resident at a time
            httpx.post(f"{OLLAMA}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=120)
        cold = chat(model, "Reply with OK.", "OK?", None, num_predict=8)
        runs = [chat(model, "You are a helpful assistant.", "Summarise this document in about 300 words:\n\n" + doc,
                     None, num_predict=400, seed=7 + i) for i in range(3)]
        js = chat(model, EXTRACT_SYS, doc, Extraction)
        out[model] = {
            "cold_load_s": round(cold.get("load_duration", 0) / 1e9, 2),
            "tok_s": round(statistics.median(r["eval_count"] / r["eval_duration"] * 1e9 for r in runs), 1),
            "json_tok_s": round(js["eval_count"] / js["eval_duration"] * 1e9, 1),
            "prefill_tok_s": round(statistics.median(r["prompt_eval_count"] / max(r["prompt_eval_duration"], 1) * 1e9
                                                     for r in runs), 1),
            "resident_gb": resident_gb(model),
        }
        print(model, out[model], flush=True)
        path.write_text(json.dumps(out, indent=2))
    cmd_report(args)


def cmd_rescore(args) -> None:
    """Recompute scores of the JSON suites from stored outputs (no model calls) after a scoring fix."""
    schemas = {"extraction": Extraction, "planning": Plan, "critique": Critique, "verify": Verdict}
    for mdir in sorted(p for p in RESULTS.glob("*") if p.is_dir() and not p.name.startswith("_")):
        for suite, schema in schemas.items():
            f = mdir / f"{suite}.jsonl"
            if not f.exists():
                continue
            items = {i["id"]: i for i in load_items(suite)}
            rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
            for r in rows:
                obj, err = parse(r.get("output", ""), schema)
                if obj is None:
                    continue
                it = items[r["id"]]
                sc = {"extraction": lambda: score_extraction(it["doc"], it["gold"], obj),
                      "planning": lambda: score_planning(it, obj), "critique": lambda: score_critique(it, obj),
                      "verify": lambda: score_verify(it, obj)}[suite]()
                r.update(sc)
            f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    cmd_report(args)


def cmd_report(args) -> None:
    rows = []
    for mdir in sorted(p for p in RESULTS.glob("*") if p.is_dir() and not p.name.startswith("_")):
        meta = json.loads((mdir / "meta.json").read_text()) if (mdir / "meta.json").exists() else {"model": mdir.name}
        row = {"model": meta["model"], "resident_gb": meta.get("resident_gb"), "cold_load_s": meta.get("cold_load_s")}
        all_res = []
        for s in SUITES:
            f = mdir / f"{s}.jsonl"
            res = [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
            all_res += res
            row[s] = round(sum(r["score"] for r in res) / len(res), 3) if res else None
            if s == "critique" and res:
                pl = [r for r in res if r.get("kind") == "planted"]
                cl = [r for r in res if r.get("kind") == "clean"]
                row["critique_detect"] = round(sum(r["score"] for r in pl) / len(pl), 3) if pl else None
                row["critique_false_alarm"] = round(1 - sum(r["score"] for r in cl) / len(cl), 3) if cl else None
            if s == "coding" and res:
                row["coding_test_fraction"] = round(sum(r.get("test_fraction", 0) for r in res) / len(res), 3)
        js = [r for r in all_res if "json_valid" in r and r["id"][0] in "epkv"]
        row["json_valid"] = round(sum(r["json_valid"] for r in js) / len(js), 3) if js else None
        timed = [r for r in all_res if r.get("out_tokens", 0) > 20]
        row["tok_s"] = round(sum(r["tok_s"] for r in timed) / len(timed), 1) if timed else None
        row["ttft_s"] = round(sum(r["ttft_s"] for r in timed) / len(timed), 2) if timed else None
        row["avg_call_s"] = round(sum(r["total_s"] for r in timed) / len(timed), 1) if timed else None
        speed = json.loads((RESULTS / "speed.json").read_text()) if (RESULTS / "speed.json").exists() else {}
        if meta["model"] in speed:  # prefer the clean speed pass over timings taken during the quality run
            sp = speed[meta["model"]]
            row.update({"tok_s": sp["tok_s"], "json_tok_s": sp["json_tok_s"], "prefill_tok_s": sp["prefill_tok_s"],
                        "resident_gb": sp["resident_gb"], "cold_load_s": sp["cold_load_s"], "speed_clean": True})
        if all(row[s] is not None for s in SUITES):
            row["quality"] = round(sum(WEIGHTS[s] * row[s] for s in SUITES), 3)
        rows.append(row)
    rows.sort(key=lambda r: -(r.get("quality") or 0))
    (RESULTS / "summary.json").write_text(json.dumps(rows, indent=2))
    cols = ["model", "quality", "extraction", "planning", "critique", "critique_detect", "critique_false_alarm",
            "verify", "coding", "coding_test_fraction", "json_valid", "tok_s", "json_tok_s", "prefill_tok_s",
            "resident_gb", "cold_load_s", "speed_clean"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |")
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


def cmd_gen_data(args) -> None:
    """Fine-tune trial data: sample N solutions per TRAIN coding task, keep only those passing the hidden tests."""
    split = json.loads((DATA / "coding" / "split.json").read_text())
    out_dir = DATA / "finetune"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"accepted_{safe(args.model)}.jsonl"
    stats = []
    with out.open("w") as f:
        for tid in split["train"]:
            tdir = DATA / "coding" / tid
            user = code_user((tdir / "task.md").read_text())
            kept, seen = 0, set()
            for k in range(args.samples):
                resp = chat(args.model, CODE_SYS, user, None, temperature=args.temperature, seed=1000 + k)
                code = extract_code(resp["message"]["content"])
                if code in seen:
                    continue
                seen.add(code)
                r = run_tests(tdir, code, RESULTS / "_gen" / safe(args.model) / tid / f"s{k}")
                if r["passed_all"]:
                    kept += 1
                    f.write(json.dumps({"task": tid, "messages": [
                        {"role": "system", "content": CODE_SYS}, {"role": "user", "content": user},
                        {"role": "assistant", "content": f"```python\n{code.strip()}\n```"}]}) + "\n")
            stats.append({"task": tid, "samples": args.samples, "unique": len(seen), "accepted": kept})
            print(f"  {tid:24s} unique={len(seen)} accepted={kept}", flush=True)
    (out_dir / f"gen_stats_{safe(args.model)}.json").write_text(json.dumps(stats, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--suites", nargs="+", default=["all"], choices=SUITES + ["all"])
    r.add_argument("--force", action="store_true", help="discard previous results for these suites")
    r.add_argument("--only", nargs="+", default=[], help="re-run only these item ids")
    sub.add_parser("report")
    sub.add_parser("rescore")
    sp = sub.add_parser("speed")
    sp.add_argument("--models", nargs="+", required=True)
    cl = sub.add_parser("coding-loop")
    cl.add_argument("--model", required=True)
    cl.add_argument("--think", action="store_true")
    cl.add_argument("--fix-rounds", type=int, default=2)
    g = sub.add_parser("gen-data")
    g.add_argument("--model", required=True)
    g.add_argument("--samples", type=int, default=8)
    g.add_argument("--temperature", type=float, default=0.8)
    args = ap.parse_args()
    {"run": cmd_run, "report": cmd_report, "rescore": cmd_rescore, "speed": cmd_speed, "gen-data": cmd_gen_data,
     "coding-loop": cmd_coding_loop}[args.cmd](args)


if __name__ == "__main__":
    main()
