# Member 10 — Final review & recovery (+ end-to-end integration) (Sprint 10)

| | |
|---|---|
| Plug-in | `backend/src/hmap/agents/review/` |
| Capability | `review.final` → `review-report` / `ReviewReport` (`CAPABILITY_OUTPUTS`); the last stub is gone |
| Strategy slot | `recovery` → `ReviewRecovery`: the task table for the review; revise / re-run / replan / ask a person when the run settles |
| Inputs | `inputs.project_tasks` (from the recovery slot), the newest `requirement-set` + `task-graph`, every step's results (`code-change-set`, `test-report` + `testing-trace`, `verification-report` + `research-report`, `doc-bundle` + `docgen-trace`), the workspace head `wsh-<project>`; `inputs.review_round` / `previous_review` (round N+1) |
| Outputs | `rr-` ReviewReport, `rev-` evidence (every item, how it was decided), `rtr-` trace (round, judge calls, plan, stop reason); `rdc-` a person's decisions; events `review.completed`, `revision.requested` |
| UI panel | `frontend/src/features/review/` — the project's **Review** tab (requirement × verdict matrix, marks, failure → step links, recovery rounds, override / accept / request changes) |
| API | `/api/review/...` ([design](design.md) §7) |
| Platform work | `scripts/demo_final.sh` / `make demo-final` (the three golden scenarios), `tests/e2e/test_golden_scenarios.py`, the contract suite `tests/e2e/contracts/`, `tests/e2e/test_no_silent_stubs.py`, [integration defects](integration-defects.md) |

Docs: [plan](plan.md) · [research](research.md) · [design](design.md) · [eval](eval.md) ·
[core requests](core-requests.md) · [integration defects](integration-defects.md). Samples:
[`samples/review/`](../../../samples/review/README.md).

## Run
```bash
cd backend && uv run pytest tests/review tests/e2e -q             # review, loop, golden scenarios, contracts, no stubs
uv run python -m tests.review.eval.run_eval                       # rules: kappa, probes, attribution, recovery (seconds)
uv run python -m tests.review.eval.run_eval --judge --name cloud  # + the judge (recorded answers)
scripts/demo_sprint_10.sh                                         # seeded failures + the closed loop + golden replay
scripts/demo_final.sh                                             # the three golden scenarios (replay); --record / --live
DEMO_TIER=single-cloud scripts/demo_final.sh                      # single-model tier: every role on Groq's Qwen (replay)
DEMO_TIER=single scripts/demo_final.sh --record                   # single-model tier on local qwen3.5:9b (hours)
```

Configuration (`.env.example`, all optional): `HMAP_REVIEW_MAX_ROUNDS`, `HMAP_REVIEW_JUDGE_SAMPLES`,
`HMAP_REVIEW_BUDGET_CALLS`, `HMAP_REVIEW_AUTO_RECOVER`, `HMAP_REVIEW_MIN_CONFIDENCE`, `HMAP_REVIEW_HOLD_ON_ESCALATE`.

## Limitations
- A test report says which **step** failed, not which requirement each test covers: a failing test step marks every
  requirement that step covers. Finer mapping needs per-test requirement ids from the testing agent.
- Constraints are checked against imports, dependencies and the language only ("don't use X", "Python", "standard
  library only"); other constraints (a port, a deadline) go to the judge, and without a model they are noted, not
  blocking.
- Deliverables only a person can make (a video, a presentation, a signature) are marked "needs a person" and never
  revised.
- On the single-model tier the judge is the producers' model (doc 02 §2.2b caveat a): objective checks decide most
  items; the judge is a different prompt and temperature.
