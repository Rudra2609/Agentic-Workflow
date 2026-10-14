# Design — refinement and observability (Member 4)

Decisions D1–D18 are in [plan.md](plan.md) §1. This page shows how the built code fits together.

## 1. Modules

```
backend/src/hmap/agents/refine/
  core.py          Critic / Reviser protocols, Attempt, Revision, RefinementResult, RefineContext (wraps the LLM in a
                   CountingLLM: tokens, calls, seconds per round), canonical JSON + digest helpers
  stop.py          MaxIters, Threshold, NoCritical, Plateau, Budget, TestsPass; any_of / all_of; default_policy();
                   best_index (regression guard); HARD_MAX_ITERS = 10 caps every loop whatever the policy
  refiner.py       the loop: produce -> critique -> classify -> stop? -> reflect -> revise; keeps the best attempt
  critics/         ProgrammaticCritic(fn), LLMRubricCritic(rubric, role="judge"), CompositeCritic (D8)
  revisers/        TargetedReviser (JSON patches at flagged paths), FullRewriteReviser, SchemaReviser,
                   StrategicReviser (targeted -> full -> widen ladder), patch.py (pointer patches, byte-identical rest)
  taxonomy.py      IssueClassifier: code rules first, then ctx.llm.classify for what the rules cannot label
  reflexion.py     ReflectionMemory (short notes via the `fast` role), InMemoryStore / ArtifactMemoryStore
  trace.py         RefineRun (superset of the RefinementTrace contract), TraceRecorder (stores each round), run ids
  integration.py   RefineSetup, refine_result(), CapabilityAdapter (D1), @refinable, RefinementMixin
  adapters/        extraction.py (Member 2's RequirementSet), plan.py (Member 3's TaskGraph)
  agent.py         RefineAgent: capability refine.run (any JSON artifact + a rubric), LRU idempotency
  router.py, diff.py, plugin.py
backend/src/hmap/agents/ops/   history.py (events + bus messages of a task), explain.py (verdict), router.py, plugin.py
backend/src/hmap/obs/          telemetry.py (OpenTelemetry), metrics.py (Prometheus registry, Sampler, serve)
frontend/src/features/refine/  Refinement tab;  frontend/src/features/ops/  Operations page
infra/docker-compose.obs.yml, infra/observability/{prometheus,grafana,load}/
```

## 2. Data flow: a checked step

```
Manager._assign ──TaskAssign(refine = project.refine or inputs["refine"])──► worker (agents process)
   worker: result = await plugin.handle(task, ctx)            # Member 2 / 3 code, unchanged
           if task.refine and result.success and a refiner serves the capability:          (D1 hook)
               result = await adapter(task, result, ctx_bound_to_refine_plugin)            # failure -> original result
   adapter (CapabilityAdapter):
       setup  = build input (document model / requirement set), load the result's artifact
       Refiner.run(input, output=artifact):
           round 0: critics on the original  ─► progress(artifact_refs=[refinement-progress]) ─► task.progress
           round n: reflect (Reflexion) → revise (targeted / full / widen) → critics → stop?
       best = keep-best; if best > base: write next version of the SAME artifact (requirement-set v2, task-graph v2)
       store refinement-trace rf-<task_id>; add its ref to the result
   ──TaskResult──► Manager (as before)
refine plug-in hooks:  task.progress with a refinement-progress ref → refine.iteration / refine.stopped events (D5)
                       task.completed of refine.run on a plan → applies the improved plan
```

The worker binds `ctx.llm` to the **refine** plug-in (`for_plugin`), so recordings go to `samples/llm_cache/refine/`
and never mix with Member 2's or 3's caches. `Cancelled` and timeouts propagate. Any other error in the adapter is
logged, and the agent's original result is reported unchanged.

## 3. Critics and scoring (D7, D8)

- **Programmatic critics run first.** Extraction: is each quote found in the document (lead-in list items accepted),
  do the marks add up to the stated total, are there no requirements (except in a pure marking rubric), duplicates,
  does the priority match the modal verb, coverage of rule hits. Plan: Member 3's `validate_plan` (cycles, unknown
  ids), `coverage` (requirement ↔ step), testable acceptance criteria.
- **The judge comes second.** `LLMRubricCritic` on role `judge`, one criterion at a time, with evidence quotes.
  Extraction rubric E1–E4 (completeness, faithfulness, kind, priority) over 12 k-character windows of the document.
  Plan rubric P1–P4 (dependencies with a data-flow hint, coverage, testable criteria, granularity).
- **Combining:** a weighted mean (judge weight 2.0 by default, 3.0 for extraction, 2.5 for plans; coverage /
  testability 0.5). A programmatic critical issue caps the score at 0.4 and a major one at 0.75. The judge's own
  issues cap more softly (0.6 / 0.85), so a single judge issue cannot sink a result that passes every code check.
- **When code and judge disagree:** a judge issue in a category a programmatic critic covers *and found clean* is
  dropped (for example "this quote is invented" when the quote was found). A judge issue that only repeats a code
  finding is dropped unless it brings new evidence, such as the missing sentence itself.

## 4. Revising and stopping (D9)

- `StrategicReviser` starts **targeted**: it only touches the flagged paths, and every unflagged item stays
  byte-identical (tested). If the same category fails again, Reflexion switches to **full** (Member 3's `replan`
  with the critique as feedback, or a full re-extraction pass). After that comes **widen** (more of the document).
- The extraction reviser makes the deterministic fixes first (priority from the modal verb, dropping exact
  duplicates). Only then does it ask the model for `add` / `drop` / `set` changes, each with guards: a new item must
  quote the document verifiably, must not repeat an existing item or a marking criterion, must be asked for by an
  issue, and must not bring back something a revision already removed.
- The plan reviser applies patch operations (`add_dependency`, `remove_dependency`, `add_criterion`,
  `replace_criterion`, `add_requirement`) to steps named in the flagged locations or hints. Then Member 3's
  `working_plan_from` and `finalize` re-validate the plan.
- The default stop policy is `any_of(Threshold 0.9, NoCritical(major), Plateau(0.02, 2), Budget(20 000 tokens, 180 s),
  MaxIters 3)`, under the hard cap of 10. Whatever stops the loop, the **best** attempt is returned (property-tested
  with hypothesis).

## 5. Storage, events, caching

| What | Where | Notes |
|---|---|---|
| Each round's output | artifact `refine-output`, id `{run_id}-out`, version n = round n-1 | the UI diff reads these |
| Live progress | artifact `refinement-progress` (`{run_id}-progress`) | its ref rides on `task.progress` (no contract change) |
| The trace | artifact `refinement-trace` (`rf-<task_id>`), `RefineRun` JSON | superset of the `RefinementTrace` contract |
| Reflexion notes | artifact `reflection-memory` (`reflections-<digest of project + capability>`) | per project, deleted with it (D6) |
| Improved result | next version of the original artifact | version 1 is kept; `applied=false` if not better |
| Events | `refine.iteration`, `refine.stopped`, `task.replayed` | written by the refine plug-in hook / the Manager |
| Cache | judge key = digest(output, rubric, prompt version, role); agent LRU by input digest | replay cache under `samples/llm_cache/refine/` |

Prompt versions: rubric critic `PROMPT_VERSION = "1"`, targeted reviser `"1"`, extraction and plan rubrics
`version="1"`. A version change changes the cache key, so old recordings are not reused by mistake.

## 6. Failure modes

| Failure | Behaviour |
|---|---|
| The judge model fails or a recording is missing | the judge is skipped; the code checks still score; the round records it (`critic_errors`, shown in the Refinement tab) |
| The reviser fails | stop reason `error`, best attempt kept |
| The adapter fails | the agent's original result is reported (logged) |
| Cancelled / task timeout | propagates; the step is handled by the Manager as before |
| A revision scores lower | not kept (regression guard); `applied=false` |
| The loop does not converge | plateau / budget / max iterations; hard cap 10 |

## 7. Observability (D11–D17)

```
API process (hmap-api) ── /metrics ──┐          agents process (hmap-agents) ── :9464/metrics ──┐
  manager.assign (root span)         │            process hmap.cap.X (consumer) → agent.handle   │
  send hmap.cap.X (producer, outbox) │            → refine.loop → chat <role> (gen_ai.* attributes) │
  manager.handle <message>           │                                                           │
        └──── OTLP/HTTP :4318 ───────┴──► Jaeger 2.22 (in memory, 256 MB) ◄──────────────────────┘
Prometheus 3.13 (scrapes host.docker.internal:8000 / :8767 / :9464, alerts.yml) ◄── Grafana 13 (:3001, anonymous viewer)
```

- **One trace per task.** The trace id is `sha256("hmap-task:" + task_id)[:32]`, set by a custom id generator. So
  every attempt, retry and replay of the task lands in the same trace, and the Ops page links to it without a lookup.
- **Spans** follow the messaging and GenAI conventions: `messaging.destination.name`, `messaging.operation.type`,
  `gen_ai.request.model`, `gen_ai.usage.input_tokens`, and so on.
- **Metrics:** counters and histograms are updated where things happen (task transitions, retries, dead letters,
  replays, dedup hits, reports, handler seconds, LLM calls / latency / tokens, refine runs / rounds / gain). A
  `Sampler` refreshes the gauges every `HMAP_METRICS_INTERVAL_S` seconds: queue depth and age of the oldest READY
  task, tasks by state, dead letters, bus DLQ, agent heartbeat age, process RSS, system RAM. Temporary event queues
  are skipped. An agent that went offline stays visible for 10 minutes, so its alert can fire.
- **Off by default.** No endpoint means no tracer and no export. The metrics port is only served by the agents
  process. Everything binds to 127.0.0.1.
- **Privacy (D17).** Spans and metrics carry ids, states, sizes, model names, token counts and error codes, and
  nothing else. `safe_attrs` drops any attribute whose key looks like text (`prompt`, `content`, `document`, `quote`, `body`, `payload`, `…text`, `api_key`, `secret`, …) and any string over 200 characters. A test exports real spans
  and metrics from a run with a secret-looking document and a fake key, and checks that neither appears. A
  `refinement-trace` is different: it is a project artifact, stored and deleted with the project, and it may quote
  that project's own document (the issues cite evidence). Telemetry never does.

## 8. Operations (D18)

`Manager.replay_dead_letter(task_id, operator, reason)` is the only way to move `DEAD_LETTERED → READY`. Blocked
dependants move `BLOCKED → CREATED`, using the same `OPERATOR_TRANSITIONS` table.

- The retry budget is reset and a **new execution** is created. Old executions stay as they were.
- A `FAILED` project goes back to `EXECUTING`.
- The event `task.replayed {by, reason, replay, previous_attempts, last_error}` records who did it and why.

The Ops "explain" view reads only what already exists: task events, executions, inbox and outbox records (dedup hits,
which process handled what), the dead-letter list and the trace id. From those it gives a verdict: status, cause,
headline, facts, and a suggestion (replay, replan or stop).
