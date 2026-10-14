# Research — what we read and what it changed in the code (Member 4)

Each topic ends with **→ code**: the place where it shows up in what we built.

## 1. Self-Refine (Madaan et al., NeurIPS 2023)
The same model writes an answer, gives feedback on it, and rewrites it, for a few rounds and with no training. It
helps most where the feedback is specific and actionable; vague feedback ("make it better") adds little. Most of the
gain comes in the first one or two rounds.
**→ code:** `Refiner` (produce → critique → revise). Issues must carry a `location` and a `fix_hint`, so the
feedback is actionable. The default is at most 3 rounds (`MaxIters(3)`), with `Plateau(0.02, 2)` stopping a loop
that has flattened.

## 2. Reflexion (Shinn et al., NeurIPS 2023)
After a failed attempt the agent writes a short note in plain words ("what went wrong, what to do differently").
The note is kept and shown on the next attempt. The gains come from an external signal of failure (tests,
environment), not from the note alone.
**→ code:** `ReflectionMemory`: notes via the cheap `fast` role (a rule-made note when there is no model), stored
per project and capability (`reflection-memory` artifact), shown to the reviser next time. When the same kind of
problem survives a round, it climbs the **strategy ladder** targeted → full → widen. The failure signal is our
programmatic critics. Measured: Reflexion ≈ Self-Refine on our sets ([eval](eval.md)).

## 3. Constitutional AI critique–revision (Bai et al., 2022) and CRITIC (Gou et al., ICLR 2024)
Critique against written principles, then revise. CRITIC's point is that critique works when it is grounded in
**tools** (search, code execution, calculators) and not in the model's own opinion.
**→ code:** the `Rubric` (written criteria, each with a weight and a default category; the judge must quote
evidence). `ProgrammaticCritic` wraps plain functions, which are our "tools": quote lookup in the parsed document,
marks arithmetic, Member 3's `validate_plan` / `coverage`.

## 4. Limits of intrinsic self-correction (Huang et al., ICLR 2024; Kamoi et al., TACL 2024)
Without external feedback, models often fail to fix their own reasoning, and sometimes turn right answers into
wrong ones. Reported gains often came from oracle labels or weak first answers. Self-correction works when the
feedback is reliable: code, tests, retrieval.
**→ code:** this is the main design rule. **Programmatic critics run first** and their findings cap the score
(critical ≤ 0.4, major ≤ 0.75). A judge issue that contradicts a clean programmatic check is dropped. **Keep-best**:
a revision that scores lower is never applied (`best_index`, tie → the earlier attempt). Refinement is off by
default. We measure on gold labels, not on the judge's own score.

## 5. LLM-as-judge biases (Zheng et al., NeurIPS 2023; Panickssery et al., 2024)
Judges prefer longer answers (verbosity), the first option (position) and **their own writing** (self-preference).
Mitigations: a different model family as judge, criterion-by-criterion scoring with evidence, and reference
answers where they exist.
**→ code:** role `judge` routes to a different family from the producer on the cloud (`qwen/qwen3.8-27b` vs
`gpt-oss-120b`). The rubric is scored one criterion at a time on a 1–5 scale with an evidence quote. There is no
pairwise comparison, so position bias does not apply. Locally there is only `qwen3.5:9b` (self-preference
unavoidable), so the code checks carry more weight. **Calibration:** in the ablation we count how often the judge's
"missing" and "should be dropped" findings were right against the gold labels.

## 6. Error taxonomies (hallucination surveys: Ji et al., 2023; Huang et al., 2023; HELM-style categories)
Separating *intrinsic* errors (contradicting the source) from *extrinsic* ones (not supported by it), and factual
from logical errors, makes feedback and statistics comparable.
**→ code:** the contract's 10 categories (OMISSION, HALLUCINATION, FACTUAL, LOGIC, REQUIREMENT_VIOLATION,
CONSISTENCY, SCHEMA, FORMAT, STYLE, SAFETY) × 4 severities. `IssueClassifier`: rules first (an unverified quote →
HALLUCINATION, a cycle → LOGIC, uncovered → REQUIREMENT_VIOLATION, …), then the `classify` role for free text.
Measured on 80 labelled issues ([eval](eval.md) §3).

## 7. Stopping rules
The common rules in the literature and in practice are fixed rounds, a score threshold, "no serious issues left", a
plateau, and a budget. Since judges are noisy, the result must be the **best** attempt, not the last one.
**→ code:** `stop.py`: `MaxIters`, `Threshold`, `NoCritical`, `Plateau`, `Budget`, `TestsPass`, `any_of` /
`all_of`, `HARD_MAX_ITERS = 10`. Hypothesis tests check that every combination stops and returns the best attempt.

## 8. Cost on small models
Each round costs a judge call plus a reviser call, and reflection adds a `fast` call. On the 9B local model a call
takes minutes (Member 3 measured ≈ 2.5 min per planning call). So refinement must be opt-in and cached.
**→ code:** the project switch "Check and improve results", off by default. The judge cache key is
digest(output, rubric, prompt version, role), so an unchanged output is never judged twice. The budget stop is
20 000 tokens / 180 s. Measured cost: [eval](eval.md) §2.

## 9. Observability
- **OpenTelemetry semantic conventions** for messaging (`messaging.system`, `messaging.destination.name`,
  `messaging.operation.type` = send / process; producer / consumer span kinds) and GenAI (`gen_ai.operation.name`,
  `gen_ai.request.model`, `gen_ai.usage.input_tokens` / `output_tokens`). → our span attributes. Prompt and
  completion content is **opt-in** in the GenAI conventions, and we never opt in (D17).
- **Trace context across a queue:** W3C `traceparent` in the message header. Producer → consumer is parent → child,
  or a link for batches. → we already carried `traceparent` on every envelope. We derive one trace id per task, so
  retries and replays share the task's trace.
- **RED** (rate, errors, duration — for request-driven services; Wilkie) and **USE** (utilisation, saturation,
  errors — for resources; Gregg). → handler / LLM rates, errors and durations (RED); queue depth, oldest READY age,
  RSS and free RAM (USE / saturation).
- **Alert on symptoms, not causes** (Google SRE book, "Monitoring Distributed Systems"); every alert links to a
  runbook. → six alerts on what a user would notice: a dead letter, a stuck queue, a lost agent, failing models,
  low memory. Each has a `runbook` annotation pointing to [runbook](runbook.md).
- **Dead-letter queues:** never replay blindly. Replay only after the cause is understood, as an explicit and
  audited action, ideally as a new attempt so the history stays intact. → D18: `replay_dead_letter` with a reason,
  a new execution, the `task.replayed` event, and a confirm dialog on the Ops page.
- **Load / soak testing:** a steady load for minutes finds leaks and queue build-up that a short burst hides. →
  `soak.py --soak-minutes`, with peak RSS, queue depth and latency percentiles.

## 10. What we decided not to do
- **Multi-agent debate** (Du et al., 2023) and a **learned stop rule** (stretch items): too costly on the laptop,
  and our gold sets are too small to train a stop rule. Not built.
- **An OpenTelemetry Collector and Alertmanager**: one more container each for no gain on one laptop. The SDK
  exports straight to Jaeger, and alerts show in Prometheus / Grafana.
