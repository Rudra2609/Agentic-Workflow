# Autonomous coding benchmark (Member 7: prepared ahead of Sprint 7, extended in Sprint 7)

**Sprint 7:** the real agent lives in `backend/src/hmap/agents/coding/` (it ported `workspace.py`, `edits.py` and
`locate.py`). This folder is now the benchmark (18 tasks), its builder and checker, the agent's eval results
(`eval_results/`, written by `backend/tests/coding/eval/run_eval.py`) and the passing trajectories
(`trajectories/<run>/<task>.json`: prompts + answers, data for Member 11). `build_sprint7_tasks.py` adds six tasks:
three greenfield tasks that start from an **empty** workspace and need more than their template (`x1_tcp_nick` is
the Definition-of-Done "TCP chat scaffold" task), and three **decoy** repositories (16–19 files with look-alike
modules and deprecated copies) for the locator. Numbers: `docs/members/7/eval.md`.

Working pieces for Sprint 7, runnable today with only Python 3.11 (standard library; no Docker, no model, no
project code):

```bash
python3 samples/coding/check_benchmark.py      # 18-task benchmark is fair + locator hit rate; prints OK
python3 samples/coding/check_tools.py          # workspace jail, command allow-list, edit applicator: 32/32
python3 samples/coding/locate.py samples/coding/tasks/b2_broadcast_crash/starter "broadcast crashes when a client disconnected"
```

## Pieces
| File | Sprint 7 item | What it does |
|---|---|---|
| `tasks/` | 7.12 | **Mini benchmark**: 12 tasks from the TCP-chat and CSV-report assignments (5 greenfield, 3 modify-existing, 4 bug-fix incl. **multi-client TCP server**, guide §32). Each has `task.json` (objective + acceptance criteria), `starter/`, `hidden_tests/` (unittest, never shown to the agent) and `gold.edits` (a reference solution in the agent's own edit format). |
| `workspace.py` | 7.1, 7.4 | **Path jail** (`..`, absolute paths, symlinks, NUL are refused) and an **allow-listed runner**: only `python3 -m unittest`, `python3 -m py_compile` and scripts inside the workspace; no shell; a scrubbed environment (no API keys reach generated code); time limit; output cap; every decision audited. |
| `edits.py` | 7.5 | **SEARCH/REPLACE edit applicator**: a unique match is required, a tolerant match is allowed for trailing whitespace or a shifted block, a syntax check runs after the edit, edits are atomic across files, and every rejection is written for the model to act on ("matches 2 places; add the surrounding lines"). |
| `locate.py` | 7.3 | BM25 file ranking over identifiers (snake/camel split), docstrings and file names: the lexical half of the hybrid locator. |
| `check_benchmark.py` | 7.12, 7.13 | Proves each task is fair, and is the runner a real agent plugs into. |
| `check_tools.py` | 7.1, 7.4, 7.5, 7.15 | Attacks and edge cases for the three tools. |

## Results
**Benchmark (`check_benchmark.py`): 18/18 tasks fair** (12 from the prep package + 6 added in Sprint 7). For every task:
1. the starter **fails** the hidden tests, for the intended reason (the planted bug, the missing feature or file;
   the multi-client task times out on the second client);
2. the gold edits **apply cleanly** through `edits.py` in a jailed workspace, with no tolerant matches needed;
3. the hidden tests then **pass**.

Locator (BM25 alone) on the 7 modify / bug-fix tasks: **top-1 7/7**, top-3 7/7; on the 3 decoy repositories: top-1 2/3,
top-3 3/3 (the agent's hybrid locator: see `docs/members/7/eval.md`).

**Tools (`check_tools.py`): 32/32.**

| Area | Checks |
|---|---|
| Path jail | `../`, nested `..`, absolute path, a symlink to `/etc/hosts`, a write through a symlinked folder, a NUL byte: all refused; normal nested writes allowed |
| Commands | `sh`, `rm`, `curl`, `python -c`, `-m http.server`, `pip install`, a script outside, `py_compile /etc/hosts`: all refused and audited |
| Environment | an API key set in the parent process does **not** reach the generated code |
| Limits | endless loop killed at the time limit; 5 MB of output capped at 10 KB |
| Edits | exact, create, create-over-existing, missing file, ambiguous (2 matches), not found (with a "closest line" hint), trailing whitespace, indentation shift (−2), syntax-breaking (rejected, and the other file's valid block is not written either), outside the workspace, malformed |

## Honest limits
- The gold edits prove the tasks are solvable; they are not an agent. pass@1 for a model is a Sprint 7 number
  (item 7.13), measured with this runner.
- The locator's 7/7 is easy mode: small repos where the bug report names the concept (`broadcast`, `median`). A
  real repo needs embeddings + LLM rerank (item 7.3).
- `workspace.py` is the lightweight Sprint 7 boundary: it has no network block and no memory or process limits.
  Hard isolation is Member 8's Docker sandbox (Sprint 8).
- Python only; tasks are small by design (the local `coder` model handles function-level work far better than
  repository-level changes).
