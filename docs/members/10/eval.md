# Evaluation — Member 10: Final review & recovery

Reproduce (`cd backend`): `uv run python -m tests.review.eval.run_eval` (rules, seconds) and
`uv run python -m tests.review.eval.run_eval --judge --name cloud` (+ the judge, recorded answers in
`samples/llm_cache/review/`). Results: `samples/review/eval_results/{rules,cloud}.json`. Golden runs:
`scripts/demo_final.sh` (replay) → `samples/review/e2e/final_replay.json`; recorded live 2026-11-01 with the team keys
→ `final_live.json`.

## 1. Sets
| Set | Where | Size | Used for |
|---|---|---|---|
| Judge calibration | `samples/review/calibration/items.jsonl` | 36 (requirement, evidence) pairs: 12 PASS, 11 PARTIAL, 13 FAIL, each with a trap tag | judge vs labels, bias probes |
| Seeded failures | `samples/review/e2e/scenarios.json` (golden TCP chat, 10 requirements, 7 steps) | 12 scenarios, 16 failures | attribution, recovery plan, stop rules |
| Golden scenarios | the TCP chat PDF, the report assignment `e2e/essay/`, a change request mid-run | 3, on the whole platform | end to end (items 10.15–10.17) |
| Contract pairs | `samples/review/contracts/` (exported from the golden run) | 8 producer outputs, 9 pairs | cross-agent contract suite (10.18) |

**The labels were re-checked one by one against their evidence on 2026-11-01: none changed.** C03's rationale was
reworded, and the six borderline calls (C03, C04, C16, C21, C24, C31) carry a `review_note` saying why they hold.
This check was not independent of whoever wrote the labels. So Member 10 signs them, and a second person labels them
(plan Q6) before the κ below may be called agreement with *human* labels. `run_eval` reports human-vs-human κ as soon
as `calibration/labels_second.jsonl` exists.

## 2. Judge vs labels (item 10.10 / 10.13)
| Judge | Accuracy | κ | FAIL → PASS | Not judged | Order-sensitive | Verbosity flips |
|---|---|---|---|---|---|---|
| objective checks only | 0.944 | **0.917** | 0 | – | – | **0 / 36** (order probe 0 / 36) |
| checks + LLM judge (the platform's setting; cloud `judge` role) | 0.944 | **0.916** | 0 | 3 (no evidence lines: not asked) | 0 | – |
| LLM judge alone on every item (what the model itself can do) | 0.806 | 0.707 | **0** | 3 | 4 | **2 / 22** judged pairs, both stricter (PARTIAL → FAIL) |

- Checks + judge: the judge decided the 2 items the checks leave open: C14 (a never-implemented requirement) now
  FAIL, right; C03 (one passing test that covers only part of the requirement) became FAIL where the label says
  PARTIAL. The remaining miss (C31, a report section that only restates the question) needs a reader: the evidence
  line says the document "shows" it.
- The judge alone is weaker (κ 0.707; it doubts 4 correct PASSes and is order-sensitive on 4 items: those are
  PARTIAL by the order-swap rule), but it **never turned a FAIL into a PASS** and padding the producer's note never
  moved a verdict toward PASS. Objective-first is what keeps the platform's number at 0.92.
- Self-preference cannot be measured on the cloud tier: the judge (`groq:qwen/qwen3.8-27b`) is not the producers'
  model. On the single-model tier it is the same model (§6).
- 11 of the 33 padded-probe calls were not answered while recording (team keys cooling down); the flips are counted
  only on the 22 pairs where both calls answered.

## 3. Attribution and recovery on the seeded failures (items 10.5, 10.6, 10.11)
| | Result |
|---|---|
| Category + responsible step right | **12 / 12 scenarios** (16 / 16 failures) — the naive "first covering step" gets **10 / 12** (blames the server for a client bug; asks the coder for a missing test) |
| Plan and outcome as expected | **12 / 12**: 9 recover to PASS (avg 1.17 rounds), 3 escalate with the right reason (plateau, oscillation, round budget) |
| Flaky timeout | re-run the tests first (round 0), not a code revision |
| Uncovered requirement | replan, no step blamed |

Same numbers as the prototype: the real modules (`hmap.agents.review`) reproduce it exactly
(`tests/review/test_failures_recovery.py`).

## 4. The closed loop on the platform (item 10.7)
`tests/review/test_loop.py` and `scripts/demo_sprint_10.sh` (real Manager + recovery slot + review agent + API,
scripted coding / testing / docs agents):
- multi-client failure in `server.py` → REVISE → **only** the server step revised (`code.revise`), test + docs + review
  re-run, the client step not → round 1 PASS → COMPLETED; `review.completed` REVISE then PASS;
- a fix that never helps → plateau after round 1 → ESCALATE, project REVIEWING → accept with notes → COMPLETED;
- a step that FAILED → re-run once with its downstream → review PASS → COMPLETED (not FAILED);
- overrides (→ new report version, project completes), request changes (→ a revision of the chosen step).

## 5. Golden scenarios on the whole platform (items 10.15–10.17)
Recorded live 2026-11-01 (team keys; Ollama stopped, so embeddings and calls that hit a cooling key took each
agent's no-model path), one plan step at a time (`HMAP_PLAN_MAX_PARALLEL=1`, see §7):

| Scenario | Live | Replay (offline) |
|---|---|---|
| 1. TCP chat PDF → … → review | REVISE (D2, D3 README / report sentences the code does not support → `docs.update` only) → **PASS**, COMPLETED, 18 tasks, 75 s | **PASS**, COMPLETED |
| 2. Report assignment (no code) | REVISE (R1 / C1 / D1 doc mismatches → the two docs steps regenerated, verify re-run) → **PASS 7/7**, COMPLETED | REVISE → **PASS**, COMPLETED |
| 3. Change request mid-run ("do not use asyncio") | replanned; 2/2 finished steps kept (same task, one execution); the review checks the request (H1) → **PASS**, COMPLETED | **PASS**, COMPLETED |

- **The final outcome replays exactly**; intermediate rounds can differ (scenario 1 replays straight to PASS): a call
  that failed while recording has no recording, so its agent takes the no-model path in replay too, but not always
  at the same point.
- Seven live recordings were made while fixing (the code changed between them, §8), so they are not repeated trials of
  one version. After the process-constraint and judge fixes (the last five): scenario 1 COMPLETED 5/5; scenario 3
  COMPLETED 3/5 (once escalated on a submission rule that doc_intel filed as a deliverable — then fixed; once on a
  plateau whose items were not inspected before the run was replaced); scenario 2 COMPLETED in the last 3 (before:
  the topic / planner / docs-rerun defects of §8). The final code's recording: all three COMPLETED.
- The multi-client **code** failure did not happen live: the coder got the server right first time. The failure →
  code revision path is shown by §4 and the seeded set (§3).
- In process (`tests/e2e/test_golden_scenarios.py`, every pre-commit, no model): all three settle with the review's
  verdict.

## 6. Single-model tier (DoD addition)
**On one cloud model: met.** `DEMO_TIER=single-cloud scripts/demo_final.sh --record` puts every chat role (reasoner,
coder, judge, fast, classify) on Groq's `qwen/qwen3.8-27b` with the team keys (Member 1's choice, 2026-11-01: the team
will not use local models for this). All three golden scenarios **COMPLETED** live (TCP chat PASS; report REVISE →
targeted docs revision → PASS 8/8; change request PASS) and again from the replay
(`samples/llm_cache/review/e2e_single`, `samples/review/e2e/final_single_cloud.json`).
- Honest reading: with one model for everything the 5 keys hit Groq's free-tier limits quickly. Only **37 calls
  answered** (reasoner 22, fast 9, judge 5, coder 1); **~180 failed** (114 of them Member 6's verify judge) and, with
  Ollama off, those steps used their no-model rules. So this run shows the platform completes on a single model; it
  says little about that model's quality. More keys, or a slower run, would let more calls through.
- Judge = producer here (no independence, doc 02 §2.2b caveat a); the objective checks decided most items.

**On the local model: not met on this laptop.** `DEMO_TIER=single` (every role `qwen3.5:9b` on Ollama): after 90 min
the TCP run had finished extraction, planning, research, verification and 4 of 6 coding steps (~14 tokens/s; coding
calls 25–316 s; each coding step ~15 min, stopped by the coding agent's time limit). The partial recording was deleted.
A full local run needs several hours or the model host (Member 11's release gate).

## 7. Cost and time
| | |
|---|---|
| Judge calls per review | 0 for items the checks decide; 2–3 per undecided item (orders alternate); budget `HMAP_REVIEW_BUDGET_CALLS` 40. Golden live runs: 0–6 judge calls per review |
| A review (replay) | < 0.1 s; live 1–10 s (judge calls) |
| A revision round | the fix + downstream re-runs + review: scenario 1 one `docs.update` + review (≈ 10 s live) |
| Rounds | ≤ `HMAP_REVIEW_MAX_ROUNDS` (2); seeded set avg 1.17 |
| Replay determinism | plan steps in parallel finish in a different order on each run → a different project head → different prompts (Sprint 7's trap); the final demo runs one step at a time |

## 8. What the evaluation changed (honest list)
Found by the full test suite, the live golden runs and the browser check, then fixed (details and owners in
[integration defects](integration-defects.md)):
- stub projects / goal-only projects / unchecked constraints made the platform wait for a person forever;
- process constraints ("groups of two", "submit before Friday") were judged FAIL and sent to the coder; the same
  rule filed as a deliverable;
- the judge answered FAIL with no evidence lines at all;
- "web frameworks are not allowed" was not checked (trailing negative, category word);
- a recovery-made replan counted as a person's change request;
- report projects: docs re-runs used `docs.update` (code-only) and made the report worse (6/8 → 2/8); the review read
  one docs bundle instead of merging the outline / section / document steps; citations written as `[C3]` not
  recognised;
- a "re-check" review counted the never-acted-on review as a round → false plateau;
- a doc mismatch on a requirement only code steps cover was sent to a coding step (browser check);
- the golden report topic (version control) had no sources in the offline corpus; the planner classed a report full
  of software words as a software project (both: scenario wording).

## 9. Honest limitations
- The calibration labels are reviewed but have one labeller (§1); κ "vs human" needs the second labeller.
- Seeded scenarios and rules were written together (12/12 is an upper bound); the golden runs are the realistic set
  and their failures were documentation ones, not code ones.
- A failing test step marks every requirement it covers (no per-test requirement ids; defect 7).
- Constraints are checked against imports / dependencies / language / word count only; others go to the judge, and
  without evidence they are noted, not checked.
- Live runs vary (requirement extraction, research, the coder): the same assignment can PASS or escalate; the
  escalation always names the reason.
