# Research: final review & recovery (Member 10, written ahead of Sprint 10)

The review agent checks finished work against the original requirements and rubric (objective evidence first, an
LLM judge second), finds which task caused each failure, and drives a bounded revision loop through the Manager.
Each topic ends with **→ plan**: what it means for Sprint 10. Working prototypes are in `samples/review/`: the
judge calibration set with bias probes, and the seeded-failure recovery loop.

## 1. LLM-as-a-Judge
- **MT-Bench / Chatbot Arena** (Zheng et al., 2023): strong models agree with human preferences about as often as
  humans agree with each other, for open-ended answers.
- **G-Eval** (Liu et al., 2023): the judge first writes evaluation steps for the criterion, then scores; it
  correlates better with humans than overlap metrics.
- **Prometheus** (Kim et al., 2024): a judge model trained to score against a **given rubric** with a reference
  answer; it showed rubric-based judging works with open models.

**→ plan:** `judge.py` judges one requirement / rubric criterion at a time with a constrained output
`{PASS | PARTIAL | FAIL, rationale, cited_evidence}`. The prompt quotes the evidence and the rubric text, and gives
no free-form overall score.

## 2. Known judge biases and fixes
- **Position bias:** the verdict changes with the order the evidence or answers are shown in (Zheng et al., 2023;
  Wang et al., 2023, "Large language models are not fair evaluators"). Fix: swap the order and require agreement,
  or average.
- **Verbosity bias:** longer, more confident text is rated higher. Fix: judge evidence, not the producer's
  description; probe with padded text.
- **Self-preference:** models favour their own outputs (Panickssery et al., 2024). Fix: the judge model ≠ the
  producer model.
- **Run-to-run variance:** fix with several samples and a majority vote.

**→ plan:**
- Order swap + 3-sample vote, and the judge uses a different model from the producer (the router's `judge` role).
- **Bias probes in the eval:** the prototype's verbosity and order probes. A naive judge reached 89 % accuracy yet
  flipped 21/36 verdicts when the producer's note was padded. The probes catch what accuracy hides.

## 3. Objective-first, evidence-grounded review
- A judge is weakest where facts can be checked mechanically, so check those mechanically: deliverable present,
  covering tests passed, claims verified, docs grounded. Use the model only for what is left (quality,
  completeness of an explanation).
- Reference-guided judging (giving the judge the acceptance criterion and the evidence) is more reliable than
  asking "is this good?".

**→ plan:**
- `checks/` runs first; `aggregate.py` lets objective signals **override** the judge on conflict.
- The prototype's rules judge alone reaches κ 0.92 on the calibration set. Its two misses (a never-implemented
  requirement, an explanation with no reasons) show exactly where the model is needed.

## 4. Measuring the judge
- **Cohen's κ** (Cohen, 1960) corrects agreement for chance: an "always PASS" judge gets κ 0 even with 33 %
  accuracy. Landis & Koch (1977): 0.61–0.80 substantial, above 0.80 almost perfect.
- Report a confusion matrix: a judge that turns FAIL into PASS is worse than one that turns PASS into PARTIAL.

**→ plan:** item 10.10 uses ≥30 labelled pairs, with **two people labelling** so human-vs-human κ is the ceiling.
Item 10.13 reports judge κ, the confusion matrix, per-trap accuracy and probe flips.

## 5. Failure analysis and attribution
- Root-cause analysis first classifies the failure, then localises it (Wong et al., 2016, fault-localisation
  survey). In a multi-agent pipeline, "localise" means **which task** produced the bad output.
- The coverage matrix (requirement → tasks) from Sprint 3 makes this a lookup, refined by evidence: which file a
  failing test exercises, which task lists the missing deliverable as an output.
- Studies of multi-agent failures (Cemri et al., 2025, "Why do multi-agent LLM systems fail?") find many failures
  come from task specification and coordination, not just bad outputs. So a requirement no task covers is a
  planning failure: **replan**, don't blame a task.

**→ plan:**
- `failure.py` taxonomy: MISSING, INCORRECT, UNTESTED, UNSUPPORTED_CLAIM, DOC_MISMATCH, QUALITY.
- Attribution = coverage matrix filtered by the capability that can fix the category, then by file / output.
- The prototype attributes 16/16 seeded failures correctly. Naive "first covering task" attribution gets 2
  scenarios wrong (client bug blamed on the server; untested requirement sent to the coder).

## 6. Recovery strategies
- Options in order of cost: **re-run** (transient: timeout, flaky test), **targeted revise** (one task with the
  failure as feedback, as in Self-Refine (Madaan et al., 2023) and Reflexion (Shinn et al., 2023)), **replan**
  (the plan itself was wrong or incomplete), **escalate** to a human.
- Re-run only what the change affects: the revised task's downstream tasks in the graph, then review.

**→ plan:** `recovery.py` builds the minimal `RevisionRequest` set (one per responsible task, with required
changes and evidence refs), computes the downstream re-run set from the task graph, and re-runs a first-time timeout
before blaming the code. It integrates through the plug-in `recovery` slot; no file under `manager/` is edited.

## 7. Bounded loops
- Revision loops can stall, oscillate (fixing A breaks B) or burn budget. Stop rules: a round budget, a **plateau**
  (same failures as last round), **oscillation** (a failure set seen before), and a cost budget.
- Member 4's `StopPolicy` already provides max rounds, plateau and budget for refinement loops.

**→ plan:** reuse `StopPolicy` and add an oscillation check. The prototype escalates on all three (plateau after 1
round, oscillation after 2, budget after 2) and always gives the reason.

## 8. Human in the loop
- Escalation is only useful if the human sees *why*: the failing requirement, the evidence, what was tried, and
  the reason the loop stopped.
- The human can override a verdict, accept with notes, or request changes (which become a revision or a replan).

**→ plan:** item 10.9 screen: requirement × verdict matrix, failure → task links, recovery timeline, and override /
accept / request-changes buttons. Overrides are stored as new labels for the calibration set.

## 9. Fitting on the laptop
- Objective checks cost nothing; the judge runs only on requirements they cannot decide (in the prototype, 2 of
  36).
- Short evidence-quoting prompts suit a 9B local model. The `judge` role can use a cloud model when keys are
  present (team routing policy), and Member 11's benchmarks decide the default.

## References
Zheng et al. 2023 (MT-Bench, LLM-as-a-Judge) · Liu et al. 2023 (G-Eval) · Kim et al. 2024 (Prometheus) · Wang et al.
2023 (LLMs are not fair evaluators) · Panickssery et al. 2024 (self-preference) · Cohen 1960 (kappa) · Landis & Koch
1977 · Wong et al. 2016 (fault localisation survey) · Cemri et al. 2025 (multi-agent failure taxonomy) · Madaan et
al. 2023 (Self-Refine) · Shinn et al. 2023 (Reflexion).
