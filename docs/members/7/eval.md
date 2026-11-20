# Evaluation — Member 7: Autonomous coding (Sprint 7, item 7.13)

Runner: `backend/tests/coding/eval/run_eval.py`. Benchmark: `samples/coding/tasks/` (18 tasks, every one checked fair
by `check_benchmark.py`: the starter fails the hidden tests, the gold edits apply and pass). Results:
`samples/coding/eval_results/*.json`. Passing trajectories: `samples/coding/trajectories/cloud/` (16 files).

| Kind | n | What it is |
|---|---|---|
| bug-fix | 4 | a bug report on a 3–5 file repo (incl. the guide's multi-client TCP bug) |
| modify | 3 | add a feature to an existing repo (incl. a two-file change) |
| greenfield | 5 | write a module into a folder with a README |
| template | 3 | **empty** folder: the agent must pick the template and go beyond it (`x1_tcp_nick` = the DoD TCP-chat scaffold) |
| decoy | 3 | bug-fix in a 16–19 file repo with look-alike / deprecated modules (locator stress) |

The agent sees the objective and acceptance criteria only; hidden tests run after it finished, in the same jailed
runner. pass@1 = seed 7, temperature 0.

## 1. Cloud `coder` route (team keys; recorded, replays offline with 0 misses)

Route: `coder` → Groq `openai/gpt-oss-120b` (Gemini flash fallback), `embed` local `nomic-embed-text`, `fast`
(rerank) cloud, `classify` (template fallback) cloud.

| Config | pass@1 | bug-fix | modify | greenfield | template | decoy | edit-apply | locator top-1 / top-3 (decoy) | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| **full** | **16/18 (0.89)** | 4/4 | 2/3 | 5/5 | 3/3 | 2/3 | 0.90 | 1.0 / 1.0 (1.0 / 1.0) | 2.1 | 2,727 |
| no locator | 17/18 (0.94) | 4/4 | 3/3 | 5/5 | 3/3 | 2/3 | 0.95 | — | 2.2 | 2,317 |
| no debug loop | 15/18 (0.83) | 4/4 | 2/3 | 5/5 | 2/3 | 2/3 | 0.90 | 1.0 / 1.0 (1.0 / 1.0) | 2.1 | 2,623 |
| BM25 only (no embeddings, no rerank) | 16/18 (0.89) | 4/4 | 2/3 | 5/5 | 3/3 | 2/3 | 0.90 | 0.9 / 1.0 (**0.67** / 1.0) | 2.1 | 2,690 |

- **The TCP-chat scaffold task (`x1_tcp_nick`) passes end to end** (DoD): empty folder → `tcp_server_client`
  template chosen by keywords → `/nick` added → hidden tests pass. Template choice 3/3.
- **Locator:** the hybrid ranking puts the right file first on every task incl. the decoys; BM25 alone gets 2 of 3
  decoys at top-1 (it ranks a look-alike first in `d2`). top-3 is perfect either way.
- **Debug loop:** used on 1 of 18 tasks (`x2_cli_top_words`: the first edit failed the template's own test; one
  debug round fixed it). Without it that task fails.
- **Edit apply:** 90 % of edits applied (first try 88 %); refusals were "SEARCH not found" and are fed back.
- **Cost:** about 2 model calls and 2.7k tokens per task; 1–5 s per task on the cloud route.

### How much to trust these numbers
- **Run-to-run noise is as large as the ablation differences.** Three full recordings of the same benchmark
  (2026-10-25, code changes in between) gave 18/18, 17/18 and 16/18. The cloud answers differ between recordings
  even at temperature 0. With n = 18 the ablation rows above say "these parts do not hurt and occasionally help"
  (locator top-1 on decoys, one debug save), not "the locator adds 5 points".
- **This benchmark is easy for a 120B model.** Tasks are small by design (the planner keeps tasks small; the
  research note's expectation for repository-level work is much lower). 2 calls per task means most tasks are solved
  by plan + one edit.
- **False success (2 of 18):** both failures were reported by the agent as `success` because its own checks
  passed: in `d2_session_minutes` the model judged that the code already did what the bug report asked (the visible
  tests are for another module), and in `m2_json_format` one of two file edits was refused and the plan was not
  finished. This is why the agent's "success" only means "my checks pass" (README) and why Member 8's tests and
  Member 10's review judge the requirement.

## 2. Local route (`qwen3.5:9b` via Ollama, not recorded)

`uv run python -m tests.coding.eval.run_eval --mode live --local-only --name local` (Ollama, M3 16 GB, ~6 tokens/s
generation). Full configuration only (ablations would take hours).

| Route | pass@1 | bug-fix | modify | greenfield | template | decoy | edit-apply | locator top-1 / top-3 | calls | time / task |
|---|---|---|---|---|---|---|---|---|---|---|
| local `qwen3.5:9b` | **10/18 (0.56)** | 3/4 | 0/3 | 2/5 | 3/3 | 2/3 | 0.58 | 1.0 / 1.0 | 2.4 | **136 s** (51–516 s) |
| cloud `gpt-oss-120b` | 16/18 (0.89) | 4/4 | 2/3 | 5/5 | 3/3 | 2/3 | 0.90 | 1.0 / 1.0 | 2.1 | ~5 s |

- The local model fixes the small bugs and does well **when a template gives it a head start (3/3)**, but fails every
  modify task and 3 of 5 greenfield tasks; only 58 % of its edits applied (it misquotes SEARCH blocks).
- It is ~30x slower: a whole TCP-chat project (7 coding steps) takes about 15–20 minutes locally.
- **Caveat:** this run started before two late fixes (no-op edits refused; "success" needs a change), so the agent
  reported `success` on all 8 tasks it failed. With the fixes some of these become `partial`; the hidden-test
  pass rate itself is what the table shows. Not recorded (local runs never are); Member 11 can re-run it.
- Conclusion (same as the bake-off and Member 5): with team keys the cloud coder does the work; the local model is a
  working fallback for small, template-shaped tasks, not for modifying existing code.

## 3. Other measurements
- **Prompt budget:** every prompt ≤ 5,500 estimated tokens (property test); the eval's largest call was 3,036
  provider tokens (prompt + answer; 3,675 by the conservative chars/3 estimate). The same prompts serve local and
  cloud. No trajectory contains a local path.
- **Replay:** the recorded eval replays with identical results and 0 misses in all four configurations; the Sprint 7
  demo replays with 0 misses (memory and RabbitMQ + Postgres).
- **Safety:** see [testing](testing.md) — jail, allow-list, environment, sandbox, limits and injection tests all
  pass; no key or absolute path in any recording or trajectory (`scripts/security_check.sh`).

## 4. Not measured (and why)
- **pass@3** (`--samples 3`, temperature 0.6): supported by the runner, not recorded (it triples the cloud calls
  for numbers the noise above already bounds). Member 11 can run it on the local route.
- **`reasoner` as the coder** (`--role reasoner`): supported, not recorded in Sprint 7.
- SWE-bench-style repository tasks: out of scope for a laptop and a 9B model.
