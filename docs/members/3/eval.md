# Evaluation — Member 3: planning and task decomposition

## 1. Gold set
`samples/planning/gold/` (see its README): 9 cases. Seven are Member 2's real outputs on Member 2's gold documents
(TCP chat — guide §32, lab manual, rubric, project brief, three-part upload, typed request, long lab sheet); two are
hand-written (work only a person can do + a low-confidence requirement; a writing project). 62 requirements in all.
Each case has a hand-made reference plan, its must-have dependencies and the requirements that must be flagged.

## 2. Metrics (`backend/tests/planning/eval/metrics.py`)
| Metric | Definition | Target (spec) |
|---|---|---|
| Validity | the shipped plan passes every hard check: acyclic, one sink = final review, known capabilities / ids / dependencies, criteria on every step | ≥ 95 % with repair |
| Coverage | requirements covered by a build / test / document step or flagged, ÷ all requirements | 100 % covered or flagged |
| Flags | precision / recall of flagged requirements vs the reference | — |
| Invented capabilities | steps assigned to a capability outside the whitelist | 0 |
| Step matching | generated steps matched one-to-one to reference steps (same phase, best requirement overlap; spine by id): precision / recall / F1 | — |
| Dependencies | "A before B" (transitive closure) between matched steps vs the reference: precision / recall / F1 | — |
| Must-edge recall | satisfied must-have dependencies (per case + generic: research → design → builds, build Rk → test Rk, tests → documents, everything → review) | "no missing obvious deps" (≥ 0.9 gate) |
| Latency | wall time per plan | — |

Dependencies are compared by reachability, not exact edges: our references put the requirements into steps one way,
the planner may split them another way, and both can be right.

## 3. Results (2026-10-13, M3 MacBook, 16 GB; prompt v2)
| Run | Models | Valid | Coverage | Flags P/R | Steps P / R / F1 | Deps P / R / F1 | Must-edge | Invented | Steps / plan | Time / plan |
|---|---|---|---|---|---|---|---|---|---|---|
| **Cloud (shipped, recorded)** | Groq `gpt-oss-120b` (Gemini answered 503) | **9/9** | **100 %** | 1.00 / 1.00 | 0.65 / 0.88 / 0.75 | 0.92 / 0.94 / **0.93** | **0.94** | 0 | 13.1 | 34 s (incl. Gemini 503 retries; Groq 1.4–5 s per call); replay 0.03 s |
| Rules only | none | 9/9 | 100 % | 1.00 / 1.00 | 0.74 / 0.77 / 0.75 | 0.94 / 0.89 / 0.91 | 0.89 | 0 | 10.9 | < 0.01 s |
| Local only (not recorded) | `qwen3.5:9b` via Ollama | 9/9 | 100 % | 0.75 / 1.00 | 0.70 / 0.83 / 0.76 | 0.92 / 0.96 / **0.94** | 0.99* | 0 | 11.9 | 172 s (≈ 2.5 min per call) |

\* The local model puts more requirements into each step, so fewer must-have dependencies apply (69 checked vs
93 for the cloud run): "build R8 before build R16" cannot fail when both are in one step. Read 0.99 as "as good as
the cloud on what applies", not better. It also flagged "the app should be deployed to AWS" as not plannable (our
reference plans it), hence flag precision 0.75. Quality is close to the cloud; the cloud buys speed (≈ 5x faster per
plan even with Gemini's 503 retries).

Per case (cloud): tcp_chat 13/13 must-edges, lab manual 5/7, rubric 2/2, project brief 11/13, multipart 9/9, request
7/7, long lab 21/23, adversarial 9/9, essay 10/10. One part fell back to rules (Part A of the multipart upload:
the model answered no steps). Every Sprint-3 target is met; `tests/planning/test_pipeline.py` keeps them as a
regression gate in replay mode.

**Prompt v1 → v2.** v1 (cloud): must-edge 0.91, dependency F1 0.91, steps F1 0.77; the essay got 17 steps for 5
requirements and the long lab missed "unit tests after the code they test" and "the model before its code"
(a backward model edge had been dropped by a rule). v2 asks for few steps, says writing tests is build work, gives
dependency guidance; model edges are kept unless they close a cycle → must-edge 0.94, dependency F1 0.93, essay 14 steps.

Reproduce (in `backend/`):
```bash
uv run python -m tests.planning.eval.run_eval --mode rules
uv run python -m tests.planning.eval.run_eval --mode replay            # recorded answers, no network
uv run python -m tests.planning.eval.run_eval --mode record            # re-records; needs the team keys
uv run python -m tests.planning.eval.run_eval --mode live --local-only # needs Ollama; never use record here
```
Per-case scores, plans, repairs and questions: `samples/planning/eval_results/*.json`.

## 3b. Replanning (spec 3.10)
Two scenarios (`REPLANS` in `run_eval.py`): the first plan's research, verify, design and first build step are
finished, then a person asks for a change. Checked: the finished steps are unchanged, the new version is valid and
fully covered, and the change happened in the unfinished part.

| Scenario | Feedback | Cloud model (recorded) | Rules only |
|---|---|---|---|
| tcp_chat | "Don't use threads; use asyncio for all networking." | applied (asyncio in the unfinished steps), 19 → 20 steps, 27 s | applied ("Do not use threads" + the full feedback as criteria) |
| long_lab | "Merge the command-line interface steps into a single build step." | applied (one CLI build step), 16 → 14 steps, 6 s | already one CLI step in the rule plan |

Both runs keep every finished step, stay valid and fully covered. Recorded with `run_eval --mode record
--replans-only` (the starting plans come from the existing recordings, so they are not re-recorded); replay test:
`test_recorded_replans_keep_finished_work_and_follow_the_feedback`.

## 4. Ablations / observations
- **Rules vs model.** The template + rules already give valid, fully covering plans with good dependencies (F1
  0.91): structure is code's job. The model adds what rules cannot know — "private messages need nicknames",
  "browse needs events to exist", "the CLI needs the parking logic" — so must-have dependencies go from 0.89 to
  0.94, and research questions become specific. It also splits work more finely than our references (step
  precision 0.65), which is a granularity difference more than an error.
- **Validator.** On the shipped run it made 4 repairs: three requirements the model left out got rule-made steps
  (long lab R1, R2; adversarial R3 "deploy to AWS"), and Part C's test step, which had no build step in its own part,
  was attached after Part B's builds. The model made no cycles. Property tests show it turns any graph into a valid one.
- **Per part vs per phase.** One call per part (1–3 calls per plan) instead of one per phase (6) keeps
  build → test links visible to the model and stays under Groq's 8 K tokens / min per key (prompts ≤ 1.6 K tokens).
- **Transitive reduction** removes 25 % of the dependencies over the gold set (222 → 166; up to 47 % on the essay)
  without changing the order.
- **Remaining misses:** project brief "browse needs organisers' events" and "the CSV of attendees needs bookings";
  lab manual "coverage is measured after the tests exist" (the model put R5 into a build step); long lab "unit
  tests after assignment and fees" (the model made the unit-test step depend on the design only).

## 5. Honest limitations
- The gold set is small and ours; the references were written by us and the prompt was tuned on them (v1 → v2).
- Effort estimates and the critical path are rough; the hours are for ordering.
- Replanning is measured on two scenarios only; the demo's own replan (after an edit, with everything finished)
  has no recording, so replay demos show the rules path there.
- Recordings come from Groq; Gemini (the first route) answered 503 the whole recording session.
