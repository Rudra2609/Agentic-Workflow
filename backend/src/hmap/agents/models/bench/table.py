"""Results → ``BenchmarkResult`` rows and the router's quality table.

Role quality from the quick set (the same 88 items for every model, so models compare on one footing):
``reasoner`` = mean(extraction, planning), ``judge`` = mean(critique, verify), ``coder`` = coding; ``fast`` and
``classify`` (short structured answers) = mean(extraction, verify), a proxy, said so in ``eval.md``. Member gold
sets are reported next to it (``sets``), not mixed in: they differ in size and in what a point means.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from hmap.agents.models.bench.common import RESULTS, SAMPLES, is_cloud
from hmap.agents.models.model import BenchRow
from hmap.core.contracts.domain import BenchmarkResult

TABLE = SAMPLES / "bench" / "table.json"
ROLE_SUITES = {"reasoner": ("extraction", "planning"), "judge": ("critique", "verify"), "coder": ("coding",),
               "fast": ("extraction", "verify"), "classify": ("extraction", "verify")}


def load_quick() -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(RESULTS.glob("quick_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data["model"]] = data
    return out


def role_scores(result: dict[str, Any]) -> dict[str, float]:
    suites = {k: v.get("score") for k, v in result.get("suites", {}).items()}
    out = {}
    for role, names in ROLE_SUITES.items():
        vals = [suites[n] for n in names if suites.get(n) is not None]
        if len(vals) == len(names):
            out[role] = round(sum(vals) / len(vals), 3)
    return out


def build_table(quick: dict[str, dict[str, Any]] | None = None, path: Path = TABLE) -> dict[str, Any]:
    quick = quick if quick is not None else load_quick()
    roles: dict[str, dict[str, float]] = {}
    for model, res in quick.items():
        for role, score in role_scores(res).items():
            roles.setdefault(role, {})[model] = score
    table = {"note": "quality per role from the quick set (samples/models/bench/results/quick_*.json); "
                     "fast / classify are a proxy (extraction + verify)", "roles": roles}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return table


def bench_rows(quick: dict[str, dict[str, Any]], sets: list[dict[str, Any]], speed: dict[str, Any]) -> list[BenchRow]:
    run_id = f"bench-{uuid.uuid4().hex[:8]}"
    rows: list[BenchRow] = []
    from hmap.agents.models.bench.quick import SUITE_ROLE

    for model, res in quick.items():
        sp = speed.get(model, {})
        for suite, s in res.get("suites", {}).items():
            if s.get("score") is None:
                continue
            rows.append(BenchRow(set_name="quick", n=s.get("answered", 0), run_id=run_id,
                                 notes="cloud" if is_cloud(model) else "local",
                                 result=BenchmarkResult(model=model, quant=res.get("quant"), role=SUITE_ROLE[suite],
                                                        task=suite, quality_score=s["score"], tok_s=sp.get("tok_s"),
                                                        ttft_s=sp.get("ttft_s"), mem_gb=sp.get("resident_gb"))))
    for r in sets:
        if r.get("score") is None:
            continue
        rows.append(BenchRow(set_name=r["set"], run_id=run_id, seconds=r.get("seconds"),
                             result=BenchmarkResult(model=r["model"], role=r["role"], task=r["task"],
                                                    quality_score=r["score"])))
    return rows
