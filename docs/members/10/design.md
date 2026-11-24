# Design — Member 10: Final review & recovery

How the `review.final` agent and the `recovery` strategy work, as built (Sprint 10). The [plan](plan.md) has the
decisions (D1–D19, P1–P7); §9 lists where the build differs from it.

## 1. The loop

```text
plan steps ─► … ─► review.final (sink) ─► run settles ─► Manager asks the recovery slot (on_settle)
                                                            │
     PASS / a person accepted ─────────────────────────────┤──► COMPLETED
     ESCALATE (stop rule, unsure attribution) ─────────────┤──► REVIEWING (waits for a person; Review tab)
     the work changed while it was reviewed (Member 8's loop)──► review again (same round)          ┐
     REVISE ─► fix tasks (code.revise / research.run / docs.update / test.run / plan.replan)        ├─► "hold":
              + downstream re-runs (test → docs) + review round N+1                                 ┘  EXECUTING
     review never ran (a step FAILED / dead-lettered) ─► re-run the failed step once + downstream + review
```

The review agent decides **what** is wrong and **who** must fix it; the strategy (inside the Manager process, with
`ManagerHandle`) creates the tasks. Revisions are ordinary tasks with `parent_task_id` = the step they fix and
`inputs.recovery = {round, review_task_id, origin_task_id, action}`; originals stay COMPLETED (their evidence is
kept). A review that has been acted on is never acted on again (the guard is a task carrying its id).

## 2. Evidence (item 10.1, `evidence.py`)

One `Item` per requirement (R), constraint (C), deliverable (D), rubric criterion (E) and human change request (H:
the feedback of a `plan.replan` task, or `inputs.change_requests`). The shape is the prototype's
(`samples/review/calibration`), so calibration, seeded scenarios and real projects go through the same code.

| Evidence | From | Notes |
|---|---|---|
| covering tasks | coverage matrix (plan ids) → Manager task ids through the task table; revisions of a step belong to it (`original_task_id`, loop origin, `parent_task_id`) | without a task table: plan ids stand in |
| tests | the **newest round** of each test → revise loop (`testing-trace.loop.round`); failing file; `pending` while Member 8's loop still runs | covers the test step's requirements + the tested coding step's |
| verification | Member 6's verdicts, claim texts from the research report | VERIFIED → supported, CONFLICTING → contradicted, else unsupported |
| docs | `DocBundle.accuracy_report.ungrounded_claims`; `docgen-trace.coverage` (shown / not shown / conflict) | ungrounded sentences go to items the docs step covers, to doc deliverables, else a synthetic `DOCS` item |
| deliverables | workspace files (`wsh-<project>`), the doc bundle | file names, README, report / docs, tests, source code; video / presentation / signature → "needs a person" |
| constraints / change requests | the code's facts (Member 9's inspector on the workspace head) | "don't / no / without / avoid X" vs imports + dependencies; "in / use <language>"; "standard library only" |
| producer note | `CodeChangeSet.notes`, through Member 5's `clean_text` | a claim, never evidence; AI-directed lines removed and counted |
| stub | every result of the covering steps written by a `stub-*` agent | PARTIAL, never revised |

## 3. Checks, judge, aggregation (items 10.2–10.4)

**Checks** (`checks/`), first decisive one wins: stub → deliverables → tests → verification → docs → constraints.
Each returns PASS / PARTIAL / FAIL / UNDECIDED with reasons and a failure category hint.

**Judge** (`judge.py`), only for UNDECIDED items and rubric levels: one item per call, G-Eval steps, JSON
`{steps, verdict, rationale, cited}`; evidence as numbered lines `E1…` wrapped as data; the producer's note shown as
a claim. Votes alternate between the given and the reversed evidence order (≥ 2, `HMAP_REVIEW_JUDGE_SAMPLES` = 3);
a cited id that is not an evidence line turns that vote PARTIAL (FAIL stays FAIL); the two orders disagreeing →
PARTIAL + `order_sensitive`; a tie → PARTIAL. No model / replay miss / budget spent → "not judged".

**Aggregation** (`aggregate.py`, table-driven): objective FAIL / PARTIAL stand; objective PASS + judge doubt →
PARTIAL; UNDECIDED → the judge's verdict, or PARTIAL "not judged". Completeness = must items (PASS 1, PARTIAL ½).
Rubric marks: the judge's level → its marks, else max × completeness ("estimated"). **Blocking** (stops a PASS): any
FAIL, any must item not PASS — except stub output, "needs a person" deliverables, and constraints / deliverables
nothing could check (noted). A must requirement with no evidence at all blocks: it is UNTESTED.

## 4. Failures and attribution (item 10.5, `failure.py`)

Category: the check's hint, else (judge only) MISSING (FAIL, nothing objective) / UNTESTED (PARTIAL, nothing
objective) / QUALITY. Responsible task: covering steps (as origins) → the capability that fixes the category
(INCORRECT → `code.*`, UNTESTED → `test.run` or the test step of a covering coding step, UNSUPPORTED_CLAIM →
`research.*`, DOC_MISMATCH → `docs.*`, MISSING → docs, then code, then tests) → for INCORRECT the coding step that
wrote the failing file (`CodeChangeSet.files_changed`). No covering step → `None` (a planning gap). Confidence 1.0
(exact) / 0.7 (several, by capability) / 0.6 (fallback).

## 5. Recovery planning and stop rules (item 10.6, `recovery.plan_round`, `stop.py`)

Per failure, cheapest first: replan (no covering step; `RevisionPlan.task_id` = the review task, plan T8) → escalate
(confidence < `HMAP_REVIEW_MIN_CONFIDENCE`) → rerun (round 0, a timeout or flaky test) → revise. Merged per
(action, task). Re-run set = descendants of the redone steps, minus the review. Items whose test loop is still
running are "waiting", not revised. Stop rules on the round's failure signature (`item:category`): plateau (same as
last round), oscillation (seen in an earlier round), round budget (`HMAP_REVIEW_MAX_ROUNDS` = 2), cost budget; when
one fires every action becomes escalate and the reason is reported. Recommendation: no blocking → PASS; any revise /
rerun / replan / waiting → REVISE; else ESCALATE.

## 6. The Manager side (item 10.7, `recovery.ReviewRecovery`)

`assign_inputs`: for `review.final`, the run's task table (id, capability, plan id, requirement ids, depends on,
parent, state, original / loop origin, recovery round, replan feedback, result artifact ids). `on_settle` (§1).
Creating the round: the fix (`code.revise` with Member 7's `revision_inputs` from the newest change set of that
step; other capabilities: a copy with `feedback`; docs → `docs.update`; tests → a copy with `generate_tests`), then
every plan step downstream (repeated until nothing changes: plan steps of one graph share a creation time), each
depending on the redone ones, then `review.final` round N+1 depending on all of them. Test runs created here carry
`inputs.loop` at Member 8's round limit, so Member 8's inner loop does not add rounds of its own (plan T5).
`revision.requested` is emitted for each fixed step.

## 7. API and UI (items 10.9, 10.12)

| Route (`/api/review`) | |
|---|---|
| `GET reports/{project}` | rounds of the current run: verdict, completeness, failures, stop reason, the tasks each round created, a person's decision |
| `GET reports/{project}/{task}` | report, every item with evidence + how it was decided + votes, the task table, trace, decision |
| `POST …/{task}/override` | one item's verdict + note → new report version (recommendation recomputed); PASS resumes the project |
| `POST …/{task}/accept` | accept with notes → `review.completed PASS (accepted_by_human)` → COMPLETED |
| `POST …/{task}/request-changes` | text + optional step → a revision of that step (+ downstream + review), or a replan |

Owner only (404 otherwise); decisions are versioned `review-decision` artifacts (overrides are the next calibration
labels). The Review tab: rounds timeline, requirement × verdict matrix (who decided: checks / judge / a person;
order-sensitive flag; the producer's claim folded away), marks, failures linked to the step (Operations explain view),
the decision box. No new npm dependency.

## 8. End-to-end (items 10.15–10.20)

- `scripts/demo_final.{sh,py}`: TCP chat (PDF), the report assignment (`samples/review/e2e/essay/`), the change
  request mid-run; every pipeline capability must be real; replay from `samples/llm_cache/review/e2e/` (one cache
  root for every agent of these inputs), `--record` / `--live`, `DEMO_TIER=single` (local only, own cache). Plan
  steps run one at a time (`HMAP_PLAN_MAX_PARALLEL=1`): parallel steps finish in a different order each run, which
  changes the project head and so the next prompts, and the recording would not replay.
- `tests/e2e/test_golden_scenarios.py`: the same three in process (replay with an empty cache: every agent's no-model
  path), so the wiring is checked in every pre-commit.
- `tests/e2e/contracts/`: every producer → consumer pair on real recorded JSON (`samples/review/contracts/`).
- `tests/e2e/test_no_silent_stubs.py`: pipeline capabilities real, stubs flagged, README table = code.

## 9. Differences from the plan
- D11 (fallback through `replace_graph`) was not needed: Member 1 wired the slot (Q1).
- D9 is simpler than planned: the Manager asks the slot only when every task is settled, so Member 8's loop is
  always finished by then; a review older than the newest finished work is re-run ("re-check"), at most 3 times.
- The slot can also answer `"COMPLETED"`: after a failed step was re-run successfully the old FAILED task would
  otherwise fail the project although the review passed.
- Stub output, "needs a person" deliverables and unchecked constraints do not block a PASS (else old demos and goal-
  only projects would wait for a person forever); a review with no requirement set passes with a note (`partial`).
- The judge runs only on UNDECIDED items (the precedence table supports judging PASS items too; not switched on).
