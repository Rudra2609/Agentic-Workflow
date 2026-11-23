# Final review & recovery samples (Member 10)

**Sprint 10 status:** these files are now the inputs of the real agent's tests and eval
(`backend/tests/review/`, `uv run python -m tests.review.eval.run_eval`): the calibration set, the seeded scenarios
(run through `hmap.agents.review`, same 12/12), `e2e/essay/` (golden scenario 2), `e2e/final_*.json` (recorded
golden runs), `contracts/` (real agent JSON for the contract suite), `eval_results/`. The prototype scripts below
still run on their own.

## The prototype (prepared ahead of Sprint 10)

Two working pieces for Sprint 10, runnable today with only Python 3.11 (no Docker, no model, no project code):

```bash
python3 samples/review/calibration/check_calibration.py        # judge calibration set + bias probes; prints OK
python3 samples/review/e2e/check_e2e.py                        # 12 seeded failures -> recovery; prints OK
python3 samples/review/e2e/review_loop.py client_side_bug      # one scenario, round by round
```

## 1. Judge calibration set (item 10.10)
`calibration/items.jsonl`: **36 (requirement, evidence) pairs** from the TCP-chat assignment, labelled PASS (12) /
PARTIAL (11) / FAIL (13), each with a rationale and a **trap** tag: a confident producer whose test fails, a long
note with nothing in it, untested claims, a test that covers only half the requirement, an unsupported or
contradicted research claim, a README with an ungrounded claim, a missing deliverable.

`check_calibration.py` scores any judge against the labels: accuracy, **Cohen's κ**, confusion matrix, per trap.
It also runs two **bias probes**, each of which must not change a verdict:
- **verbosity**: the producer's note is padded with confident filler;
- **order**: the evidence lists are reversed (position bias).

| Judge | Accuracy | κ | Verbosity flips | Order flips |
|---|---|---|---|---|
| `rules`: objective evidence first (the deterministic layer of the design) | 94 % | **0.92** | 0 | 0 |
| `always_pass` (bad baseline) | 33 % | 0.00 | 0 | 0 |
| `trust_producer` (believes long confident notes) | 89 % | 0.83 | **21** | 0 |

The `trust_producer` row is the point. On accuracy alone it looks fine, but padding the note flipped 21 verdicts.
**Accuracy alone does not show bias, and the probes do.** The rules judge's two misses are exactly the cases that
need someone to read the content: a requirement that was never implemented, though no test says so, and a report
section that only restates the question. That is the job of the LLM judge in Sprint 10.

## 2. Seeded failures → recovery (item 10.11)
`e2e/base.json` is the golden scenario:
- 10 requirements and a 7-task graph (research → verify; server; client; test; docs; review);
- the coverage matrix (requirement → tasks);
- the evidence when everything passes.

`e2e/scenarios.json` holds 12 seeded failures with the expected result. `review_loop.py` runs each round:
**judge → classify** (MISSING / INCORRECT / UNTESTED / UNSUPPORTED_CLAIM / DOC_MISMATCH) **→ responsible task**
(coverage matrix + which file failed / who makes the missing deliverable) **→ minimal recovery plan** (one revision
per responsible task; re-run only their downstream tasks) **→ stop rule**.

| Scenario | What happens |
|---|---|
| multi_client_unsupported (guide §32) | revise server, re-run test + docs → PASS |
| client_side_bug | /msg fails only in `client.py` → blame the **client** task, not the server |
| untested_requirement | ask the **test** task for a test, not the coder for a change |
| two_failures_one_round | two revisions, shared downstream re-run once |
| missing_readme / hallucinated_doc_claim | revise docs only, nothing else re-runs |
| unsupported_research_claim | revise research, re-run verify + docs |
| flaky_timeout | first timeout → re-run the tests before blaming the code |
| uncovered_requirement | no task covers it → **replan**, do not blame a random task |
| stuck_fix | same failure after a fix → **escalate (plateau)** |
| oscillating_fixes | R2, R3, R2... → **escalate (oscillation)** after 2 rounds |
| slow_progress | progress, but the round budget (2) runs out → **escalate (budget)** |

Result: **12/12 as expected**: 16 failures classified and attributed correctly, 9 recover to PASS, and 3 escalate
with a reason. The check is not trivially passing: replacing attribution with "the first covering task" fails 2
scenarios, and removing the flaky re-run rule fails 1.

## Honest limits
- The labels were written with the data and re-checked one by one against the evidence on 2026-11-01: no label
  changed (C03's rationale reworded; the six borderline calls carry a `review_note`). That check was not
  independent of the author, so Member 10 still signs them off and a second person should label them
  (`calibration/labels_second.jsonl`, `{"id", "label"}` per line) before κ is called agreement with human labels.
- The scenarios and the rules were written together, so 12/12 is an upper bound. In Sprint 10 the evidence comes
  from real agents (`TestReport`, `VerificationReport`, `DocBundle`).
- The "world after each revision" is scripted; no agent really revises anything here. The Manager integration
  (item 10.7) is the Sprint 10 work.
