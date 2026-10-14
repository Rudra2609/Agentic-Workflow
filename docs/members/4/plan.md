# Sprint 4 plan of action — Member 4: Self-reflection & refinement (+ observability)

Spec: [`docs/sprints/sprint-04-member4-self-reflection-refinement.md`](../../sprints/sprint-04-member4-self-reflection-refinement.md).
Goal: a reusable **produce → critique → classify → revise → stop** library (`agents/refine/`) that any agent can wrap
around its output, applied to Member 2's extraction and Member 3's plan behind `refine=true` with a **measured
ablation**; plus the platform's **observability & operations** (traces, metrics, alerts, "why did this fail", DLQ
replay, runbook). Written 2026-10-13 against the code as handed over after Sprint 3.

Items marked **(M1)** touch paths Member 1 owns (`ownership.toml`). **Decision (2026-10-13): Member 4 makes these
changes itself, as part of Sprint 4**, and lists them in the commit message (no separate change log). Member 2's and
Member 3's folders are still not edited: the D1 hook makes that unnecessary.

**Status (2026-10-14): built** following §1 — see [README](README.md), [research](research.md), [design](design.md),
[eval](eval.md), [testing](testing.md), [integration](integration.md), [runbook](runbook.md). Differences from this
plan: span names follow the OpenTelemetry conventions (`send` / `process hmap.cap.X`, `chat <role>` instead of
`bus.publish` / `bus.consume` / `llm.call`); the explain route is `/api/ops/explain/{task_id}` (plug-in routes may not
start with `/tasks`); Reflexion notes are keyed by project + capability (`reflections-<digest>`); two more alerts than listed in
4.19 (`HmapBusDeadLetters`, `HmapLowMemory`); gateway option `HMAP_LLM_RECORD_MISSING` added to record
only missing answers.

---

## 0. What already exists (do not rebuild)

| Piece | Where | What it gives Member 4 |
|---|---|---|
| Contracts | `core/contracts/domain.py` | `Issue{category, severity, description, location, evidence, fix_hint}`, `IssueCategory` (the 10 taxonomy values), `Severity` (info/minor/major/critical), `Critique{score, issues, critic}`, `RefinementSpec`, `RefinementIteration`, `RefinementTrace{iterations, best_iteration, stop_reason}` — fixed in Sprint 1, additive changes only |
| Events / capability | `events.py`, `capabilities.py` | `refine.iteration`, `refine.stopped` declared; `refine.run` declared; nobody serves / emits them yet |
| Refine flag | `TaskAssign.refine: bool = False` | exists in the message, **but the Manager never sets it** |
| LLM roles | `core/config.py` | `judge` (cloud: `qwen/qwen3.8-27b` → a different family from the `reasoner`'s; local: same `qwen3.5:9b`), `fast`, `classify` (`ctx.llm.classify(state, questions)` → typed answers) |
| Usage accounting | `LLMResponse.usage{input_tokens, output_tokens, latency_s, model, provider, cached}` | token / time budgets per refinement |
| Replay cache | gateway `record` / `replay` per plug-in | `samples/llm_cache/refine/` is Member 4's |
| M2 critics-to-be | doc_intel: quote location (`extract/quotes.py`), marks-sum check in the contract, `validate.py`, gold set + `tests/doc_intel/eval` | programmatic critics + ablation harness for extraction |
| M3 critics-to-be | planning: `validate.validate_plan`, `coverage.coverage`, `replan.replan(feedback=…)`, gold set + `tests/planning/eval` | programmatic critics, a targeted reviser, ablation harness for plans |
| Progress → events | `TaskProgress.artifact_refs` are copied into the `task.progress` event | refinement iterations can be published without a contract change |
| Tracing ids | `core/tracing.py`: W3C `traceparent` on every envelope, `child_traceparent` | OpenTelemetry spans can reuse the ids |
| Queue depths, DLQ | `bus.queue_depths()`, `bus.dead_letters()`, `GET /api/dead-letters` | metrics + the DLQ view without touching RabbitMQ config |
| Chaos scenarios | `backend/tests/e2e/test_chaos.py` (agent crash, duplicate delivery, retries exhausted → DLQ, Manager restart, late report) | the cases the "why did this fail" view must explain |
| Infra | `infra/docker-compose.yml` (Postgres, RabbitMQ), `make infra-up` | the obs stack is a **separate** compose file Member 4 owns (`infra/docker-compose.obs.yml`, `infra/observability/**`) |

Downstream users (from their sprint files) — the interface must serve them:
Sprint 5 (Refiner on synthesis, citation critic), Sprint 6 (Refiner), Sprint 7 (Refiner self-review hook, **StopPolicy**
and **Reflexion notes** in its debug loop), Sprint 8 (**StopPolicy** + plateau in the code↔test loop), Sprint 9 (Refiner
with a grounding critic), Sprint 10 (Refiner, judge biases), Sprint 11 (issue categories confirmed by programmatic
critics as labelled data for a classifier; re-uses the load / soak script), mid-evaluation (extraction / plan **with vs
without** refinement as a timeline + metric delta; Jaeger / Grafana during failure injection).

---

## 1. Decisions (recommendations; settle before Phase C)

| # | Topic | Recommendation | Why / alternative |
|---|---|---|---|
| D1 | Applying refinement to M2/M3 without editing their code (4.10) | **(M1)** a new plug-in field `refiners: dict[capability, RefineAdapter]`; the agent runtime (`core/runtime/worker.py`) runs the adapter on the agent's result **when `task.refine` is true**, before reporting the result. Member 4's plug-in registers adapters for `document.extract` and `plan.generate` | The spec allows owners' code to be touched "only via the documented hook" — this *is* that hook, owned by the platform, so M2/M3 folders stay untouched. Alternative (editing their agents) breaks ownership |
| D2 | New agents opting in (4.8) | `@refinable(spec_factory)` decorator **and** `RefinementMixin` in `agents/refine/integration.py` — 5 lines in the agent's own `handle` | For Members 5, 7, 9 who write new agents; D1 is for agents that already exist |
| D3 | Where `refine` comes from | **(M1)** project setting `refine` (dashboard toggle "Check and improve results — slower"), overridable per task by `inputs["refine"]`; the Manager copies it into `TaskAssign.refine`. Default **off** | Each iteration costs ~2 model calls; the mid-eval shows on vs off |
| D4 | Iteration output storage | `refinement-trace` artifact (`RefinementTrace`, versioned once per iteration); each iteration's output as its own artifact (`output_ref`) | Contract already has `output_ref`; versions let the UI diff revisions; deleted with the project |
| D5 | `refine.iteration` / `refine.stopped` events (4.9) | The runtime adapter / decorator sends a `TaskProgress` with the trace artifact ref; a Member-4 hook on `task.progress` turns it into `refine.iteration` / `refine.stopped` events with `{task_id, iteration, score, issues_by_category, stop_reason}` | No contract or Manager change; progress is already persisted as events |
| D6 | Reflexion memory (4.5) | Notes stored as a `reflection-memory` artifact per project + key (capability + task signature); retrieved for the next attempt / retry / similar task in the same project. **No migration** | "Postgres/artifact" — artifacts keep it per project and delete with it (privacy); a `004_*` table only if cross-project lessons are wanted later |
| D7 | Critic model | `LLMRubricCritic` uses `role="judge"`: on the cloud a different model family from the producer (self-preference); locally it is the same `qwen3.5:9b`, so **programmatic critics first** and the LLM critic only for what code cannot check (spec insight) | Optional: `HMAP_ROLE_MAP judge=…` to a different local model if RAM allows; documented, not default |
| D8 | Score aggregation (`CompositeCritic`) | weighted mean of critic scores, but **any programmatic `critical` / `major` issue caps the score** (critical → ≤ 0.4, major → ≤ 0.75) and LLM issues contradicting a programmatic pass are dropped | "programmatic issues override LLM opinion" |
| D9 | Default stop policy | `max_iters=3` · `threshold≥0.9` · `no critical issues` · `plateau(Δ<0.02 for 2)` · `budget(tokens 20k, 180 s)` · cancellation; always **return the best iteration**, regression guard | Spec §6 (≤3 iterations); best-of-N retention (spec §9) |
| D10 | Caching | key = hash(output) + hash(rubric) + prompt version, in the agent's memory LRU + gateway replay cache | Spec §6 |
| D11 | Observability code location | **(M1, ownership.toml)** a new Member-4 package `backend/src/hmap/obs/` (telemetry setup, metrics registry, no-op when disabled) + `backend/tests/obs/`; the core only calls `obs.span(...)` / `obs.metric(...)` at a few points (bus publish/consume, worker handle, gateway call, Manager transitions) | Keeps OpenTelemetry out of core logic; a slip in obs never blocks the library ("kept deliberately separate") |
| D12 | Ops UI / API location | **(M1, ownership.toml)** a second Member-4 plug-in `agents/ops/` (router `/api/ops/…`) + `frontend/src/features/ops/` (a Page "Operations"), separate from `refine` | Separation required by spec §5b |
| D13 | Traces backend | Jaeger **v2** all-in-one (`jaegertracing/jaeger:2.22.0`, in-memory, OTLP on 4317/4318); Python `opentelemetry-sdk 1.45.x` + OTLP/HTTP exporter, **off unless `HMAP_OTEL_ENDPOINT` is set** | One container, native OTLP; no collector needed |
| D14 | Metrics + alerts | `prometheus_client 0.26` `/metrics` on the API process and the agents process; Prometheus `v3.13.4` scrapes them (queue depths via `bus.queue_depths()`, so RabbitMQ config is untouched); **Prometheus alert rules** (visible in Prometheus / Grafana) — no Alertmanager | Fewest containers on a 16 GB laptop; alerts "fire in a demo" |
| D15 | Dashboards | Grafana `13.0.x` with provisioned datasources (Prometheus, Jaeger) and a committed dashboard JSON; anonymous viewer, no admin password in git (`HMAP_GRAFANA_PASSWORD` in `.env`) | Spec 4.17 "dashboard JSON committed" |
| D16 | RAM | obs containers capped (Jaeger 256 MB, Prometheus 256 MB, Grafana 256 MB), started only with `make obs-up` (profile `obs`) | Doc 02: open during failure injection "if RAM allows" |
| D17 | Privacy in telemetry | spans / metrics carry ids, sizes, model, tokens, states — **never prompts, document text, artifact contents or keys** (key fingerprints only) | CLAUDE.md rule; documents can be private |
| D18 | DLQ replay (4.18) | **(M1)** `Manager.replay_dead_letter(task_id, operator)`: a new transition `DEAD_LETTERED → READY` allowed **only** through this call; a **new execution** (attempt counter kept, retry budget reset), event `task.replayed {by, reason}`, dependants `BLOCKED → CREATED` re-evaluated | Research: "never replayed blindly" — explicit, audited, new execution id |

---

## 2. Changes in Member 1's code (done by Member 4, listed in the commit message)

1. **Dependencies:** `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` (1.45.x),
   `prometheus-client` 0.26, `psutil` 7.2 (RAM metric).
2. **Ownership:** add `backend/src/hmap/obs/**`, `backend/tests/obs/**`, `backend/src/hmap/agents/ops/**`,
   `backend/tests/ops/**`, `frontend/src/features/ops/**` to `[members.4]`.
3. **Refinement hook (D1):** `Plugin.refiners`; the worker runs the adapter when `task.refine`; adapters get the
   `TaskAssign`, the agent's `TaskResult` and the `AgentContext`, and return a (possibly) new `TaskResult`.
4. **Refine flag (D3):** `ProjectRecord.refine` (+ API create/patch, dashboard toggle) and `inputs["refine"]`
   → `TaskAssign.refine` in `Manager._assign`.
5. **Telemetry call sites (D11):** spans in bus publish/consume, worker handle, gateway call; Manager transition
   counters; `/metrics` routes on the API and agents processes. All no-ops when obs is off.
6. **DLQ replay (D18):** `replay_dead_letter`, the transition, `task.replayed` event, core tests.
7. **Make targets / env:** `make obs-up` / `obs-down` / `obs-open`; `.env.example`: `HMAP_OTEL_ENDPOINT`,
   `HMAP_METRICS_PORT`, `HMAP_GRAFANA_PASSWORD`, `HMAP_REFINE_DEFAULT`.
8. **Demo:** `scripts/demo_sprint_4.sh` / `.py` (scripts/demo* is shared with Member 9 — list it).

---

## 3. Phases

### Phase A — Research and design
`docs/members/4/research.md`, each topic with what it changes in the code:
- Self-Refine (Madaan et al. 2023), Reflexion (Shinn et al. 2023), Constitutional-AI critique–revision (Bai et al.
  2022), CRITIC — tool-interactive critiquing (Gou et al. 2024).
- **Limits of intrinsic self-correction** (Huang et al. 2024 "LLMs cannot self-correct reasoning yet"; Kamoi et al.
  2024 survey): gains come from external feedback → programmatic critics first.
- LLM-as-judge biases (self-preference, verbosity, position; Zheng et al. 2023) → different judge model, rubric
  per criterion with evidence.
- Error taxonomies (e.g. hallucination taxonomies; HELM-style categories) → our 10 categories × 4 severities.
- Stopping rules: max-iterations, threshold, plateau, budget, regression guard (keep best).
- Cost / benefit on small local models (measured in Phase G).
- Observability: OpenTelemetry semantic conventions (messaging, GenAI), RED / USE metrics, alerting on symptoms,
  DLQ handling / replay patterns.

`docs/members/4/design.md`: modules, data flow, the hook (D1), events, storage, prompts with versions, budgets, failure
modes, obs architecture diagram. **Done when:** D1–D18 settled; every module and test named.

### Phase B — Gold sets and evaluation harness (before the loop)
- **Taxonomy sample set** `samples/refine/taxonomy_gold.jsonl`: ~80 labelled issues (all 10 categories, 4 severities)
  taken from real critic outputs on M2/M3 gold + hand-written ones (for 4.7 accuracy).
- **Ablation harness** `backend/tests/refine/eval/`: runs M2's pipeline (`tests.doc_intel.eval`) and M3's planner
  (`tests.planning.eval`) as producers; conditions **base · Self-Refine · Self-Refine + Reflexion**; metrics = each
  owner's own quality metric (M2: requirements F1, criteria F1, quote verification; M3: validity, coverage,
  dependency F1, must-edge recall) + iterations, tokens, latency, stop reasons. Modes rules / replay / record / live.
- **Done when:** `run_eval --condition base` reproduces M2/M3's published numbers.

### Phase C — Core library (4.1–4.4, 4.6)
- `core.py` (4.1): `Critic` / `Reviser` / `StopPolicy` protocols, `Issue` / `Critique` (re-export the contracts),
  `RefinementResult{final_output, best_index, trace, stop_reason}`, `RefineContext` (llm, budget, cancel, progress).
- `refiner.py` (4.2): the loop — produce (or take a given output) → critics → classify → stop? → revise → … with
  per-iteration trace (score, issues, tokens, seconds), cancellation (`ctx.check_cancelled`), token / time accounting
  from `LLMUsage`, keep-best; deterministic with `FakeLLM`.
- `critics/` (4.3): `ProgrammaticCritic(fn, name)`, `LLMRubricCritic(rubric, role="judge")` (criterion-by-criterion
  JSON with evidence quotes; issues must cite a location), `CompositeCritic(weights)` with D8.
- `revisers/` (4.4): `FullRewriteReviser`, **`TargetedReviser`** (only flagged locations: JSON-pointer / span patches,
  unflagged parts byte-identical — tested), `SchemaReviser` (constrained JSON with the contract's schema + repair).
- `stop.py` (4.6): `MaxIters`, `Threshold`, `NoCritical`, `Plateau(eps, k)`, `Budget(tokens, seconds)`,
  `TestsPass(fn)`, combinators `any_of` / `all_of`, `default_policy()`; regression guard; **hypothesis property tests:
  every policy combination terminates within max_iters (hard cap) and returns the best iteration**.
- **Done when:** library unit tests green; deterministic traces.

### Phase D — Taxonomy, Reflexion, integration (4.5, 4.7, 4.8)
- `taxonomy.py` (4.7): rules first (schema error → SCHEMA, unverified quote → HALLUCINATION, missing requirement →
  OMISSION, cycle → LOGIC, uncovered → REQUIREMENT_VIOLATION, …), then `ctx.llm.classify` (role `classify`) for free-
  text LLM issues; accuracy on the taxonomy gold set; logs (state, question, answer, rule-confirmed label) for Sprint 11.
- `reflexion.py` (4.5): after a failed / low-score attempt, a short verbal note ("what failed, what to change") via
  `fast`; stored (D6); injected into the next attempt's revise prompt; **repeated same-category failure → strategy
  change** (e.g. targeted → full rewrite; widen context) — tested.
- `integration.py` (4.8): `@refinable`, `RefinementMixin`, `RefineAdapter` base used by D1; dry-run for Member 5 in
  ≤ 10 lines documented (`docs/members/4/integration.md`).

### Phase E — Trace, events, agent, adapters (4.9, 4.10, 4.12)
- `trace.py` (4.9): build / store `RefinementTrace` (+ per-iteration output artifacts); progress messages carrying the
  trace ref; plug-in hook → `refine.iteration` / `refine.stopped` (D5).
- `adapters/` (4.10):
  - **extraction** (`document.extract`): critics = quote verification against the document model, marks-sum / total,
    contract validation, empty-set check (programmatic) + LLM rubric "missing requirements / wrong kind / wrong
    priority" over the document text; reviser = targeted patch of the `RequirementSet` (add / fix / drop items, each new
    item must quote verifiably).
  - **plan** (`plan.generate`): critics = `validate_plan`, `coverage`, size / branching (programmatic) + LLM rubric
    "missing dependencies / over-split / acceptance criteria not testable"; reviser = `replan.replan(feedback=critique)`
    (Member 3's public API) then `finalize`.
  - Both behind `refine=true` via D1; base behaviour unchanged when off (tested).
- `agent.py` (4.12): `RefineAgent` for `refine.run` — input: an output artifact + `RefinementSpec` / rubric in inputs;
  output: the improved artifact + `refinement-trace`; idempotent (cache D10); on the bus.

### Phase F — API + UI (4.13)
- `router.py` (`/api/refine`): traces of a project / task, one trace with iterations, an iteration's output, diff
  between two iterations (JSON diff), project `refine` setting proxy if needed.
- `frontend/src/features/refine/` (tab "Refinement"): per refined task a **timeline** of iteration cards (critique
  summary, issues grouped by category with severity colours, evidence), **score curve** (small SVG line chart), stop
  reason, best-iteration marker, **diff of each revision**; Simple vs Developer mode; light / dark; phone width.
- **Done when:** lint / typecheck / tests / build pass; checked by hand with screenshots.

### Phase G — Ablation, tests, demo (4.11, 4.14, DoD)
- Record refine calls (`samples/llm_cache/refine/`) on the M2 + M3 gold sets (cloud), one local-only run (not recorded).
- `docs/members/4/eval.md`: table base vs Self-Refine vs +Reflexion — quality delta, iterations, tokens, latency, stop
  reasons, judge agreement with programmatic critics; **honest if the gain is small or null**; taxonomy accuracy.
- Tests `backend/tests/refine/` (4.14): termination + plateau + regression guard (property), critics, revisers
  (unflagged parts untouched), stop combinators, reflexion strategy change, taxonomy, adapters on/off, decorator,
  trace + events, agent idempotency, API (ownership 404, CSRF), integration over RabbitMQ + Postgres with
  `refine=true`; Sprint 1–3 suites unchanged.
- `scripts/demo_sprint_4.sh`: the TCP chat PDF with `refine=true` → extraction and plan timelines, improved score.

### Phase H — Observability & operations (4.15–4.20, separate track)
- **4.15 traces:** `hmap.obs.telemetry` (tracer provider, OTLP/HTTP exporter, resource attrs), span helpers; spans:
  `bus.publish` / `bus.consume` (messaging conventions), `agent.handle`, `llm.call` (model, tokens, cached — no
  prompt), Manager transitions as events on the span; one task shows Manager → agent → LLM in Jaeger (test with an
  in-memory span exporter).
- **4.16 "Why did this task fail?"** (`/api/ops/tasks/{id}/explain` + Ops page): final state → last error record →
  executions (attempts, agents, timeouts, superseded) → message attempts (inbox / outbox, dedup hits) → trace link →
  artifacts; verified on every `test_chaos.py` scenario.
- **4.17 metrics + Grafana:** gauges / counters — queue depth and age per capability, retries, DLQ count, dedup hits,
  heartbeat age per agent, task states, LLM latency histogram + tokens by role / provider, process RSS + system RAM;
  `infra/observability/grafana/dashboards/hmap.json` committed.
- **4.18 DLQ replay UI + runbook:** Ops page lists dead letters (own projects), "Replay as a new attempt" with a
  reason (confirm dialog) → `replay_dead_letter`; `docs/members/4/runbook.md` (what each alert means, how to
  inspect, when to replay vs stop vs replan, how to start / stop obs).
- **4.19 alerts:** `infra/observability/prometheus/alerts.yml` — DLQ > 0, heartbeat expired, queue age > N s for 2 min,
  LLM error rate; demonstrated firing in the demo (kill an agent / poison a task).
- **4.20 load / soak (STRETCH):** `infra/observability/load/soak.py` — N concurrent projects on stub agents, records
  throughput, p95 latency, RAM, errors → `eval.md`; reused by Sprint 11.
- `infra/docker-compose.obs.yml` (profile `obs`, 127.0.0.1 only, memory caps) + provisioning; `make obs-up` (M1).
- **Done when:** `make obs-up` starts the stack in one command; Jaeger shows a task trace; Grafana shows the
  dashboard; an alert fires; the explain view answers every chaos scenario; replay creates a new execution.

---

## 4. Definition of Done (spec §8 + §5b + project rules)
- [x] Ablation shows a measured effect (positive or honestly null) on both M2 and M3
- [x] Every loop provably terminates; the best iteration is retained (property tests)
- [x] Member 5 can integrate in ≤ 10 lines (dry-run in `integration.md`)
- [x] `demo_sprint_4.sh`: extraction / plan with `refine=true` shows the timeline and an improved score
- [x] `obs` profile starts with one command; Jaeger / Grafana usable during failure injection
- [x] Recorded answers in `samples/llm_cache/refine/`; tests and demo need no network / keys / Ollama
- [x] No prompt, document text or key in any span, metric, log or trace artifact (a `refinement-trace` is a project
  artifact and may quote that project's own document as evidence; telemetry never does — design §7)
- [x] `scripts/precommit.sh --member 4` clean; `scripts/check_sprint.sh 4` PASS

## 5. Interface handed on (spec §7)
```python
from hmap.agents.refine import Refiner, ProgrammaticCritic, LLMRubricCritic, TargetedReviser, default_policy
refiner = Refiner(producer=..., critics=[ProgrammaticCritic(check_citations), LLMRubricCritic(RESEARCH_RUBRIC)],
                  reviser=TargetedReviser(), stop=default_policy())
result = await refiner.run(input, ctx)      # result.final_output, result.trace, result.stop_reason
```
Also: `StopPolicy` usable without a `Refiner` (Members 7, 8 loops); `ReflectionMemory` (Member 7's debug loop);
`@refinable` / `RefinementMixin`; `Plugin.refiners` for existing agents; `refine.*` events; policy defaults in config;
taxonomy-labelled `classify` data for Member 11; the soak script for Member 11; Jaeger / Grafana for the mid-eval.

## 6. Order and effort
| Order | Phase | Effort |
|---|---|---|
| 1 | Settle D1–D18; Member-1 requests (hook, flag, ownership, deps, DLQ replay, telemetry call sites) | medium |
| 2 | A research + design | medium |
| 3 | B taxonomy set + ablation harness | medium |
| 4 | C core library | large |
| 5 | D taxonomy, Reflexion, integration | medium |
| 6 | E trace, events, agent, adapters | large |
| 7 | F API + UI | medium |
| 8 | G ablation, tests, demo | medium–large |
| 9 | H observability & ops (parallel track; 4.20 stretch) | large |

## 7. Risks
| Risk | Mitigation |
|---|---|
| Small models rubber-stamp their own work | Programmatic critics first; a different judge family on the cloud; rubric with evidence; measure judge vs programmatic agreement |
| Runaway cost / time | Budget stop, ≤ 3 iterations, caching, off by default |
| Reviser breaks good parts | Targeted patches, unflagged parts byte-identical (tested), keep best iteration |
| Gain is zero on our gold sets (they are already high) | Report honestly; include harder cases (rules-only producer, local model) where there is room to improve |
| Ownership friction (core hooks) | D1 / D11 / D12 keep Member 4's logic in its own folders; core changes are small call sites |
| 16 GB RAM with obs + Ollama | Obs is optional, memory-capped, off by default; one command up / down |
| Telemetry leaks private data | D17; a test scans exported spans / metrics for prompt text and key patterns |
| Gemini 503 / quotas while recording | Record on Groq / Gemini with fallback; replay keeps tests offline |

---

## 8. Verification — is anything missing?
Every requirement in the spec (and every downstream need) mapped to where this plan covers it.

| Spec / need | Covered by | Built |
|---|---|---|
| §1 produce → critique → classify → revise → stop; Self-Refine + Reflexion; hybrid critics; taxonomy; stopping | C (refiner, critics, revisers, stop), D (taxonomy, reflexion) | ✓ |
| §3 research topics incl. limits of self-correction, cost on small models | A (research.md), G (measured cost) | ✓ |
| §3 key insight: programmatic first | D7, D8, adapters in E | ✓ |
| §4 Refiner signature, Critic types, Reviser, StopPolicy list (max_iters, threshold, no critical, plateau, budget, tests_pass), ReflectionMemory | C (`core.py`, `refiner.py`, `critics/`, `revisers/`, `stop.py` incl. `TestsPass`), D (`reflexion.py`) | ✓ |
| §4 taxonomy 10 × 4 | existing contract types; D (`taxonomy.py`) | ✓ |
| 4.1 core abstractions typed + docs | C | ✓ |
| 4.2 loop, trace, token / time accounting, cancellation, deterministic | C (`refiner.py`) + FakeLLM tests | ✓ |
| 4.3 Programmatic / LLMRubric / Composite with override | C + D8 | ✓ |
| 4.4 full-rewrite, targeted patch, constrained-schema; no regression of unflagged parts | C (`revisers/`) + test | ✓ |
| 4.5 Reflexion, strategy change, stored | D + D6 | ✓ |
| 4.6 stop policies, combinators, plateau, regression guard, property tests | C (`stop.py`) + hypothesis tests | ✓ |
| 4.7 classifier rule + `classify`, sample-set accuracy | B (taxonomy gold), D | ✓ |
| 4.8 `@refinable` / `RefinementMixin`, `refine=true`, 5-line integration | D (`integration.py`), D1, D3 | ✓ |
| 4.9 `RefinementTrace` artifact + `refine.iteration` / `refine.stopped`, visible in UI | E (`trace.py`), D4, D5, F | ✓ |
| 4.10 M2 + M3 adapters, owners' code only via the documented hook | E (`adapters/`), D1 | ✓ |
| 4.11 ablation base vs Self-Refine vs +Reflexion; quality, iterations, tokens, latency; honest | B harness, G, `eval.md` | ✓ |
| 4.12 `RefineAgent` `refine.run` on the bus | E (`agent.py`) | ✓ |
| 4.13 API + UI timeline (critique, issues by category, score curve, stop reason, diff) | F | ✓ |
| 4.14 tests incl. integration over the bus | G | ✓ |
| Stretch: debate, learned stop, per-agent defaults in config, critic calibration | Per-agent defaults in config: in D9 / M1 request 7 (`HMAP_REFINE_DEFAULT` + per-capability defaults in the plug-in); critic calibration: judge-vs-programmatic agreement in G; debate and learned stop: **not planned** (stretch) | ✓ per-agent defaults, critic calibration; debate / learned stop not built (as planned) |
| 4.15 OpenTelemetry bus / handlers / gateway, Jaeger `obs` profile | H, D11, D13 | ✓ |
| 4.16 "why did this task fail" for the chaos scenarios | H | ✓ |
| 4.17 Prometheus + Grafana, listed metrics, dashboard JSON | H, D14, D15 | ✓ |
| 4.18 DLQ replay UI + runbook, new execution | H, D18 | ✓ |
| 4.19 alert rules firing in a demo | H, D14 | ✓ |
| 4.20 load / soak (stretch) | H | ✓ |
| §5b DoD: obs one command; Jaeger / Grafana in the mid-eval | H, D16, M1 request 7 | ✓ |
| §6 judge role, `fast` for tagging, ≤ 3 iterations, cache by output + rubric hash | D7, D4 (`classify` for tagging per 4.7; `fast` for reflections), D9, D10 | ✓ |
| §7 interface + contracts + events + policy defaults in config | §5 of this plan | ✓ |
| §8 DoD (ablation, termination, M5 ≤ 10 lines, demo) | §4 of this plan | ✓ |
| §9 risks | §7 of this plan | ✓ |
| Mid-eval: with vs without refinement + Jaeger / Grafana during failure injection | D3 toggle, F timeline, G demo, H | ✓ |
| Sprint 5 / 6 / 9 Refiner; Sprint 7 / 8 StopPolicy + Reflexion standalone; Sprint 10 judge biases; Sprint 11 labelled classify data + soak script | §5 interface, D (logging of rule-confirmed labels), H (4.20) | ✓ |
| Project rules: no git by Claude, keys only in `.env`, stop background processes, replay for tests | DoD list; D17 | ✓ |

Gaps found while checking (now in the plan):
- `TaskAssign.refine` existed but nothing set it → M1 request 4 (D3).
- No sanctioned way to refine M2/M3 without editing their folders → D1 hook.
- `refine.*` events need a publisher → D5 via progress + hook (no contract change).
- Observability code has no owned home in the backend → D11 / D12 ownership additions.
- Dead-lettered tasks are terminal in the state table → D18 explicit replay transition.
- The judge falls back to the same local model as the producer → D7 says so and leans on programmatic critics.
- Demo scripts are shared with Member 9 (`scripts/demo*` cross-cutting) → M1 request 8 lists it.
