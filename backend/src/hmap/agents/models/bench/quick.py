"""The quick set (item 11.5): the §0 bake-off's 88 items through the platform gateway, for any model.

Same prompts, schemas, settings (temperature 0, seed 42, ``think`` off, no repair retries) and scoring code as
``scripts/model_bakeoff.py``, so a local model here reproduces its bake-off score (checked by a test on the
recordings). The suites map to roles: extraction / planning → ``reasoner``, critique / verify → ``judge``, coding →
``coder``. Quality = the bake-off's weighted mean.

A call the model did not answer (a cloud route rate limited past the retries) is **not scored**, and the summary
says how many: an unanswered item is not a wrong answer.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hmap.agents.models.bench.common import RESULTS, bakeoff, gateway_for, slug
from hmap.core.config import LLMMode, Settings
from hmap.core.errors import HmapError
from hmap.core.llm.base import Role

SUITE_ROLE: dict[str, Role] = {"extraction": "reasoner", "planning": "reasoner", "critique": "judge", "verify": "judge",
              "coding": "coder"}


def _prompt(mb: Any, suite: str, item: dict[str, Any]) -> tuple[str, str, type[BaseModel] | None, int]:
    if suite == "extraction":
        return mb.EXTRACT_SYS, item["doc"], mb.Extraction, 2048
    if suite == "planning":
        user = json.dumps({k: item[k] for k in ("requirements", "constraints", "deliverables", "notes") if k in item},
                          indent=1)
        return mb.PLAN_SYS, user, mb.Plan, 2048
    if suite == "critique":
        return mb.CRITIC_SYS, f"TASK:\n{item['context']}\n\nOUTPUT TO REVIEW:\n{item['artifact']}", mb.Critique, 1024
    if suite == "verify":
        return mb.VERIFY_SYS, f"CLAIM: {item['claim']}\nQUOTE: {item['quote']}", mb.Verdict, 512
    return mb.CODE_SYS, mb.code_user((item["dir"] / "task.md").read_text()), None, 2048


def _score(mb: Any, suite: str, item: dict[str, Any], text: str, parsed: Any, work: Path) -> dict[str, Any]:
    if suite == "coding":
        return dict(mb.run_tests(item["dir"], mb.extract_code(text), work / item["id"]))
    if parsed is None:
        return {"score": 0.0, **({"kind": "planted" if item.get("planted") else "clean"} if suite == "critique"
                                 else {})}
    fn = {"extraction": lambda: mb.score_extraction(item["doc"], item["gold"], parsed),
          "planning": lambda: mb.score_planning(item, parsed), "critique": lambda: mb.score_critique(item, parsed),
          "verify": lambda: mb.score_verify(item, parsed)}[suite]
    return dict(fn())  # type: ignore[no-untyped-call]


async def run_quick(model: str, base: Settings, *, mode: LLMMode = "replay", suites: list[str] | None = None,
                    limit: int | None = None, retries: int = 3, wait_s: float = 20.0,
                    work: Path | None = None) -> dict[str, Any]:
    mb = bakeoff()
    gw = gateway_for(model, base, mode)
    work = work or Path("/tmp") / "hmap_bench_work" / slug(model)
    out: dict[str, Any] = {"model": model, "mode": mode, "suites": {}, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    for suite in suites or list(SUITE_ROLE):
        items = mb.load_items(suite)[:limit] if limit else mb.load_items(suite)
        rows = []
        for item in items:
            system, user, schema, num_predict = _prompt(mb, suite, item)
            msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            resp, err = None, ""
            for attempt in range(retries + 1):
                try:
                    resp = await gw.generate(SUITE_ROLE[suite], msgs, schema=schema, temperature=0.0, seed=42,
                                             max_tokens=num_predict)
                    break
                except HmapError as exc:
                    err = f"{type(exc).__name__}: {str(exc)[:160]}"
                    if "Replay" in type(exc).__name__ or "JSON" in err or "Validation" in err \
                            or "structured" in err.lower() or attempt == retries or mode == "replay":
                        break
                    await asyncio.sleep(wait_s)
            if resp is None and ("Validation" in err or "JSON" in err or "structured" in err.lower()):
                rows.append({"id": item["id"], "answered": True, "json_valid": False, "score": 0.0, "error": err,
                             **({"kind": "planted" if item.get("planted") else "clean"} if suite == "critique"
                                else {})})
                continue
            if resp is None:
                rows.append({"id": item["id"], "answered": False, "error": err})
                continue
            sc = _score(mb, suite, item, resp.text, resp.parsed, work)
            rows.append({"id": item["id"], "answered": True, "json_valid": schema is None or resp.parsed is not None,
                         **sc, "latency_s": resp.usage.latency_s, "out_tokens": resp.usage.output_tokens,
                         "cached": resp.usage.cached})
        out["suites"][suite] = summarise(suite, rows, mb)
        out["suites"][suite]["rows"] = rows
    out["quality"], out["coverage"] = quality(out["suites"], mb)
    await gw.aclose()
    return out


def summarise(suite: str, rows: list[dict[str, Any]], mb: Any) -> dict[str, Any]:
    scored = [r for r in rows if r.get("answered")]
    s: dict[str, Any] = {"items": len(rows), "answered": len(scored),
                         "valid_json": round(sum(bool(r.get("json_valid")) for r in scored) / len(scored), 3)
                         if scored else None}
    if not scored:
        s["score"] = None
        return s
    s["score"] = round(sum(float(r["score"]) for r in scored) / len(scored), 3)   # the bake-off's suite score
    if suite == "critique":
        planted = [r for r in scored if r.get("kind") == "planted"]
        clean = [r for r in scored if r.get("kind") == "clean"]
        s["catch"] = round(sum(r["score"] for r in planted) / len(planted), 3) if planted else None
        s["false_alarm"] = round(1 - sum(r["score"] for r in clean) / len(clean), 3) if clean else None
    if suite == "coding":
        s["test_fraction"] = round(sum(float(r.get("test_fraction", 0)) for r in scored) / len(scored), 3)
    lat = [r["latency_s"] for r in scored if r.get("latency_s") and not r.get("cached")]
    if lat:
        s["median_latency_s"] = round(sorted(lat)[len(lat) // 2], 2)
    return s


def quality(suites: dict[str, Any], mb: Any) -> tuple[float | None, float]:
    """The bake-off weighted mean over the suites that were scored, and the weight share they cover."""
    have = {k: v["score"] for k, v in suites.items() if v.get("score") is not None}
    w = sum(mb.WEIGHTS[k] for k in have)
    if not w:
        return None, 0.0
    return round(sum(mb.WEIGHTS[k] * v for k, v in have.items()) / w, 3), round(w, 2)


def save(result: dict[str, Any], name: str | None = None) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"quick_{name or slug(result['model'])}.json"
    path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return path
