"""Benchmark command line (items 11.5, 11.6).

    cd backend
    uv run python -m hmap.agents.models.bench.run quick --models qwen3.5:9b groq:qwen/qwen3.8-27b --mode record
    uv run python -m hmap.agents.models.bench.run quick --models qwen3.5:9b --mode replay     # zero model calls
    uv run python -m hmap.agents.models.bench.run sets --models groq:openai/gpt-oss-120b --sets m6_verify m10_judge
    uv run python -m hmap.agents.models.bench.run speed --models qwen3.5:4b qwen3.5:9b        # Ollama up, swap low
    uv run python -m hmap.agents.models.bench.run table                                       # router quality table
    uv run python -m hmap.agents.models.bench.run quant --variants qwen3.5:4b qwen3.5:9b

Results: ``samples/models/bench/results/`` (quick_*, speed.json, quant.json), ``samples/models/bench/sets/``,
``samples/models/bench/table.json``. Recordings: ``samples/llm_cache/models/<model>/``.
"""

import argparse
import asyncio
import json

from hmap.agents.models.bench import quant, quick, sets, speed, table
from hmap.agents.models.bench.common import RESULTS
from hmap.core.config import Settings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quick")
    q.add_argument("--models", nargs="+", required=True)
    q.add_argument("--mode", choices=("replay", "record", "live"), default="replay")
    q.add_argument("--suites", nargs="*")
    q.add_argument("--limit", type=int)
    q.add_argument("--wait-s", type=float, default=20.0, help="pause before retrying a rate-limited call")
    s = sub.add_parser("sets")
    s.add_argument("--models", nargs="+", required=True)
    s.add_argument("--sets", nargs="+", default=list(sets.GOLD_SETS), choices=list(sets.GOLD_SETS))
    s.add_argument("--timeout-s", type=float, default=1200.0)
    sp = sub.add_parser("speed")
    sp.add_argument("--models", nargs="+", required=True)
    sp.add_argument("--runs", type=int, default=3)
    sub.add_parser("table")
    qt = sub.add_parser("quant")
    qt.add_argument("--variants", nargs="+", required=True)
    args = ap.parse_args()
    base = Settings.from_env()
    if args.cmd == "quick":
        for model in args.models:
            res = asyncio.run(quick.run_quick(model, base, mode=args.mode, suites=args.suites, limit=args.limit,
                                              wait_s=args.wait_s))
            path = quick.save(res)
            print(f"{model}: quality {res['quality']} (weight covered {res['coverage']}) "
                  f"{ {k: v['score'] for k, v in res['suites'].items()} } -> {path.name}", flush=True)
    elif args.cmd == "sets":
        sets.run_sets(args.models, args.sets, timeout_s=args.timeout_s)
    elif args.cmd == "speed":
        res = asyncio.run(speed.measure(args.models, base, runs=args.runs))
        path = RESULTS / "speed.json"
        old = json.loads(path.read_text()) if path.exists() else {}
        RESULTS.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**old, **res}, indent=1) + "\n")
    elif args.cmd == "table":
        print(json.dumps(table.build_table(), indent=1))
    else:
        sp_path = RESULTS / "speed.json"
        rep = quant.report(table.load_quick(), json.loads(sp_path.read_text()) if sp_path.exists() else {},
                           args.variants)
        (RESULTS / "quant.json").write_text(json.dumps(rep, indent=1) + "\n")
        print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
