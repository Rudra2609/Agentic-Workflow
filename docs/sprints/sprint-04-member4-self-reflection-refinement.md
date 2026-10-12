# Sprint 4 — Member 4: Self-Reflection & Iterative Refinement

**Owner:** Member 4 · **Needs:** Sprint 3 accepted · **Unblocks:** Sprint 5 (research synthesis), Sprints 7–9 (code/doc self-review)
**Deliverable type:** a **reusable library** (`agents/refine/`) + a thin agent for standalone use. Not a pipeline stage by itself.

## 1. Goal
Provide a framework any agent can wrap around its output: **produce → critique → classify issues → revise → decide stop**, with Self-Refine and Reflexion strategies, hybrid (programmatic + LLM) critics, an error taxonomy, and stopping criteria — and **prove with an ablation** that it improves M2/M3 outputs.

## 2. Provided by earlier sprints
Gateway (`role=fast|reasoner|judge`), M2 extraction + gold set, M3 planning + gold set + validators (usable as programmatic critics), artifact store (for traces), UI shell.

## 3. Research deliverable
Self-Refine (iterative feedback/refine), Reflexion (verbal memory of failures), critique-revision/Constitutional-style, CRITIC (tool-assisted critique), limits of intrinsic self-correction (LLMs often can’t self-correct reasoning without external signal), error taxonomies, stopping rules (max-iter, plateau, threshold, budget), cost/benefit on small local models.

**Key design insight to document:** with 7–8B models, *LLM-only* self-critique is weak → **prefer external verifiers first** (schema validators, M3 DAG checks, tests, string-match of quotes) and use the LLM critic for what can’t be checked mechanically.

## 4. Design

```python
class Refiner:
    def __init__(self, producer, critics: list[Critic], reviser, stop: StopPolicy, memory: ReflectionMemory|None): ...
    async def run(self, task_input, ctx) -> RefinementResult   # final_output, trace, stop_reason

Critic.review(output, task_input, ctx) -> Critique{score:0-1, issues:[Issue{category,severity,location,evidence,fix_hint}]}
  ├─ ProgrammaticCritic(fn)        # validators, DAG/schema checks, test runners
  ├─ LLMRubricCritic(rubric, role="judge")   # criterion-by-criterion scoring w/ evidence
  └─ CompositeCritic(weights)      # programmatic issues override LLM opinion
Reviser.revise(output, critique, history) -> output'   # targeted: only touch flagged parts
StopPolicy: max_iters | score>=θ | no critical issues | plateau(Δscore<ε for k) | budget(tokens/time) | tests_pass
ReflectionMemory (Reflexion): per-task episodic notes "what failed & strategy change", injected into next attempt
```
Error taxonomy: `FORMAT, SCHEMA, OMISSION, HALLUCINATION, FACTUAL, LOGIC, REQUIREMENT_VIOLATION, CONSISTENCY, STYLE, SAFETY` × severity `{info, minor, major, critical}`.

## 5. Work items

### MUST
| # | Item | Files (`agents/refine/`) | Acceptance |
|---|---|---|---|
| 4.1 | Core abstractions: `Critic`, `Reviser`, `StopPolicy`, `Issue`, `Critique`, `RefinementResult` | `core.py` | typed; docs |
| 4.2 | `Refiner` loop (Self-Refine) with trace capture, token/time accounting, cancellation-aware | `refiner.py` | deterministic with FakeLLM |
| 4.3 | Critics: Programmatic, LLMRubric, Composite (programmatic-overrides) | `critics/` | unit tests |
| 4.4 | Reviser strategies: full-rewrite, **targeted patch** (revise flagged spans), constrained-schema reviser | `revisers/` | doesn’t regress unflagged parts |
| 4.5 | Reflexion memory + strategy-change prompts; stores in Postgres/artifact | `reflexion.py` | repeated failure → changed approach |
| 4.6 | Stop policies + combinators; **plateau & regression guard** (keep best iteration, not last) | `stop.py` | property tests: always terminates |
| 4.7 | Error classifier (rule + LLM via `ctx.llm.classify`) mapping issues → taxonomy | `taxonomy.py` | labelled sample set accuracy |
| 4.8 | `@refinable(...)` decorator / `RefinementMixin` so any `BaseAgent.handle` can opt in via task flag `refine=true` | `integration.py` | 5-line integration |
| 4.9 | `RefinementTrace` artifact + events (`refine.iteration`, `refine.stopped`) | `trace.py` | visible in UI |
| 4.10 | **Apply to M2 (extraction) and M3 (plan)**: critics = M2 validators/source-quote check; M3 DAG/coverage validators + LLM rubric; additive flag in their agents (owners’ code touched only via the documented hook) | `agents/refine/adapters/` | works behind `refine=true` |
| 4.11 | **Ablation experiment**: on M2 + M3 gold sets compare base vs Self-Refine vs Self-Refine+Reflexion: quality metric, iterations, tokens, latency | `tests/refine/eval/` | table in `eval.md`; honest if gain small |
| 4.12 | `RefineAgent` capability `refine.run` (generic: input = output artifact + rubric) for the Manager to use standalone | `agent.py` | on bus |
| 4.13 | API + UI: refinement timeline (iteration cards: critique, issues by category, score curve, stop reason, diff of revision) | `agents/refine/router.py` (auto-mounted), `frontend/src/features/refine/` (auto-registered) | |
| 4.14 | Tests: loop termination, plateau, memory, adapters, integration over bus | `tests/refine/` | green |

### STRETCH
Multi-critic debate; learned stop policy from traces; per-agent default policies in config; critic calibration vs gold.

## 5b. Platform-wide responsibility: Observability & Operations (also owned by Member 4)

Why here: error classification and trace analysis are this member's research area, and the **mid-evaluation** needs these views. Kept deliberately separate from the refinement library so a slip here never blocks it.

| # | Item | Acceptance |
|---|---|---|
| 4.15 | **OpenTelemetry** across bus publish/consume, agent handlers, LLM-gateway calls (W3C `traceparent` already in the envelope from Sprint 1); Jaeger container (`obs` compose profile) | one task shows spans Manager→agent→LLM |
| 4.16 | **"Why did this task fail?" view**: final state → error record → execution → message attempts → trace → artifacts (Member-1 research §11) | works for the Sprint-1 chaos scenarios |
| 4.17 | **Prometheus + Grafana**: queue depth/age, retries, DLQ count, dedup hits, heartbeat age, LLM latency/tokens, RAM | dashboard JSON committed |
| 4.18 | **DLQ replay UI + operator runbook** (explicit new-execution, never blind replay — §26) | replay creates a new execution |
| 4.19 | Alert rules (DLQ>0, heartbeat expiry, sustained queue age) | fire in a demo |
| 4.20 | Load/soak script (N concurrent projects on stub agents) with findings | numbers in `eval.md`; **STRETCH** if time is short |

Definition of Done addition: `obs` profile starts with one command; mid-eval demo can open Jaeger/Grafana during the failure-injection step.

## 6. Local-LLM notes
Critic = `role="judge"` (prefer different model than producer to reduce self-preference); `fast` for taxonomy tagging; keep iterations ≤3 by default (each costs 2 LLM calls); cache by (output hash, rubric hash).

## 7. Interface handed to Member 5 (and later 7, 9, 10)
```python
refiner = Refiner(producer=..., critics=[ProgrammaticCritic(check_citations), LLMRubricCritic(RESEARCH_RUBRIC)], reviser=TargetedReviser(), stop=default_policy())
result = await refiner.run(input, ctx)
```
Contracts: `RefinementSpec`, `RefinementTrace`; events `refine.*`; policy defaults in config.

## 8. Definition of Done (additions)
- [ ] Ablation shows measured effect (positive or honestly null) on both M2 and M3
- [ ] Every loop provably terminates; best-iteration retained
- [ ] M5 can integrate in ≤10 lines (dry-run documented)
- [ ] Demo `demo_sprint_4.sh`: extraction/plan with `refine=true` shows timeline + improved score

## 9. Risks
Small models rubber-stamp their own work → programmatic-first critics, different judge model; runaway cost → budget stop + caps; reviser regresses good parts → targeted revision + best-of-N retention.
