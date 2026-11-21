# Evaluation — automated testing & execution (Sprint 8 item 8.13)

`backend/tests/testing/eval/run_eval.py`, results in `samples/testing/eval_results/` (`cloud.json` = the run that
recorded the loop answers with the team keys; `replay-check.json` = everything again from the recordings, both
backends). Measured 2026-10-30 on the presenter laptop (Colima, 16 GB).

## Detection and classification
| Set | What | Docker | Local runner |
|---|---|---|---|
| Seeded (good + 15 variants, labelled) | faulty variants detected | **15/15 (100 %)** | 15/15 |
| | classified as labelled (incl. the good one as PASS) | **16/16** | 16/16 |
| | false pass on the known-good version | **0** | 0 |
| Unseen (Member 7's 3 bug-fix + 3 decoy bug-fix + 3 modify tasks, hidden tests) | starters detected as failing | **9/9** | 9/9 |
| | gold-fixed versions: false alarms | **0/9** | 0/9 |
| | seconds per pipeline run (all stages, one container) | 1.13 s | 0.96 s |

DoD: ≥ 90 % of seeded failures detected → 100 %; 0 false-pass on known-good → 0.

Notes:
- Every seeded failure has a hint, and except the assertion failures (which point at the test line, by design) the file and
  line point at the faulty line of `chatproto.py`. Coverage of the good version: 100 % (Docker; the local runner has
  no `coverage`).
- On the unseen set the categories look right on inspection: off-by-one / median / discount / minutes / CSV quotes /
  max clients → ASSERTION at the failing check; the broadcast crash and the two modify tasks whose feature is missing
  → CRASH at the line that raised (`room.py:27`, `protocol.py:17`, `report.py:20`). They were not labelled
  beforehand, so this is an inspection, not a measured accuracy.
- The 3 security variants pass all their unit tests; only the security stage catches them (built-in rules on both
  backends, bandit in Docker). Without that stage they would be false passes.
- Sandbox overhead: a whole pipeline (static, build, unit with coverage, security) costs about 1.1 s in Docker vs
  1.0 s on the local runner: the container start is ~0.15 s on Colima; running the tests dominates.

## The loop (test → `code.revise` → test), seeded variants with an actionable failure
14 variants (all but the good one and the lint-only one), each revised by Member 7's coding loop from the testing
agent's required changes (category, test, place, expected vs actual, hint), at most 2 rounds; fixed = every stage
passes and the test file was not touched. Cloud `coder` (gpt-oss-120b on Groq, Gemini fallback).

| Run | Fixed | Rounds needed |
|---|---|---|
| recording run (live answers) | **14/14 (100 %)** | 12 in one round; `shell_injection` and `hardcoded_secret` in two (the first fix removed `shell=True` but kept a shell-like command / moved the secret into another constant) |
| replay from the recordings | **13/14 (93 %)** | `race_condition` misses: its failure text is the number of threads that won the race (`assert 20 == 1`, `19 == 1`, …), different on every run, so the revision prompt never matches the recording and the replayed loop runs without a model |

**Local model** (`qwen3.5:9b` through Ollama, `--local-only`, local runner, not recorded), 4 representative variants,
1 round each (`samples/testing/eval_results/local.json`): **2/4 fixed** — `syntax_error` (24 s) and `name_error`
(94 s) yes; `off_by_one` (38 min: most answers ran into the 2,000-token limit, the edit never applied) and
`insecure_eval` (3 min, the `eval` stayed) no. A full 14-variant local run was started and stopped after 70 minutes
(about 5 minutes per coding call, most calls hitting the token limit); the cloud coder is the practical choice for the
loop, and the local model works for the simple compile / name errors.

The loop on a real project (the Sprint 8 demo): the coding agent's TCP chat server fails the assignment's multi-client
acceptance test (no `/who`), the model hint says what the test expects, one revision adds `/who`, the re-test passes
7/7 and the loop stops (Docker and local runner, both replayed with 0 misses apart from the locator's embeddings).

## Stretch checks (`--extras`, Docker; `samples/testing/eval_results/extras.json`)
| Check | Result |
|---|---|
| Mutation score of the seeded suite's own 8 tests (30 mutants) | **21/30 caught (70 %)**, 23 s. Not caught: 5 × `not x -> x` in nickname / command checks (lines 17, 25, 41), `>= / >` and `4 -> 5` on the frame-header length (line 67), `> -> >=` at line 41, one `return None` (line 46): concrete gaps a teacher could add tests for |
| JS / TS classification (good, wrong result, syntax, crash, eval, lint, TS type error) | **7/7**, 0.5–2 s per run |
| Fuzzing, 4 functions: 3 with edge-case bugs (`mean([])`, `first_word('')`, `initials('a  b')`) and one that raises its own error correctly | **3/3 found**, **0 false findings** |
| Dependency audit against the real OSV (one manual check) | `requests==2.19.0` → 1 finding ("pin to 2.32.4 or newer"), `lodash 4.17.15` → 1 finding listing 5 advisories ("pin to 4.18.0"); unpinned `flask>=2`, `express@^4` listed as not audited |
| gVisor (`runsc`, installed 2026-10-31) | every sandbox test passes (36/36); detection, mutation, JS, fuzz results identical to runc; +29 % per pipeline run, +32 % mutation, +76 % JS; container start 0.106 s vs 0.093 s ([gvisor.md](gvisor.md)) |

## Honest limits
- The rules were written next to the seeded suite (16/16 is not a fair accuracy number); the unseen set is the fair
  check, and it has only 18 runs.
- Generated tests were checked by unit tests (gate keeps tests that fail on a stub, drops tests that pass on it) but
  not measured on the benchmark: every benchmark workspace has tests, so generation never triggers there.
- The local-model loop number is from 4 variants, 1 round (above), not the full 14.
- Flaky detection was tested with a scripted backend; the seeded race fails deterministically (5/5 in the
  prototype), so no real flaky test was observed.
