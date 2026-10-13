# Sprint 3 plan of action — Member 3: Planning & task decomposition

Spec: [`docs/sprints/sprint-03-member3-planning-task-decomposition.md`](../../sprints/sprint-03-member3-planning-task-decomposition.md).
Goal: a `RequirementSet` → a **validated, traceable `TaskGraph`** (hierarchical tasks, dependencies, priorities,
capabilities, acceptance criteria, roadmap, coverage matrix) produced by a real `plan.generate` agent, approved or
edited by a human, then run by a **layer-parallel DAG executor** that replaces Member 1's naive one. Written 2026-10-13.

**Status (2026-10-13): built** following §1 — see [README](README.md), [design](design.md), [eval](eval.md), [testing](testing.md).

Everything here was checked against the code as handed over after Sprint 2 (`HANDOFF.md`, `manager/`,
`agents/pipeline/`, `core/contracts/domain.py`). Items marked **(M1)** are outside Member 3's paths
(`ownership.toml`); Member 3 lists them in the commit message.

---

## 0. What already exists (do not rebuild)

| Piece | Where | What it gives Member 3 |
|---|---|---|
| `TaskGraph` / `PlanTask` / `Roadmap` / `Phase` / `Milestone` contracts | `core/contracts/domain.py` | Flat task list; `depends_on` is the only edge source (`edges` is computed); the contract already rejects duplicate ids, unknown deps, unknown coverage ids and cycles |
| Pipeline hooks | `agents/pipeline/plugin.py` | `document.extract` done → creates the `plan.generate` task with the RequirementSet + DocumentModel refs; `plan.generate` done → `submit_graph(require_approval=True)`. **Do not add hooks for these steps** |
| Manager graph handling | `manager/manager.py` `submit_graph`, `approve`, `_reconcile_project` | Creates one task record per `PlanTask` (in `executor.order()` order), gates them with `needs_approval`, auto-approves when the project says so, reconciles ready / blocked / outcome through the `GraphExecutor` protocol |
| Executor slot | `manager/executor.py` (`GraphExecutor` protocol: `order`, `ready`, `blocked`, `outcome`) + `Plugin(provides={"executor": ...})` | Member 3 plugs in; without the planning plug-in the naive executor is used |
| Assignment | `manager/assignment.py` | Priority (`urgent > high > normal > low`) then age; stub agents have `max_slots = 4`, so different **and** same-capability tasks can overlap |
| Approval API | `POST /api/projects/{id}/approval`, `POST /api/projects/{id}/plan` (core) | Approve / reject with comment; raw graph submission |
| Event names | `core/contracts/events.py` (`plan.approved`), `capabilities.py` (`plan.replan`) | Declared, **not emitted / served by anyone yet** |
| Plan view in the dashboard | `frontend/src/components/Workflow.tsx` (`PlanGraph`), `lib/workflow.ts` (`layoutGraph`) — Member 1 | Read-only dependency graph of the *running* tasks. Member 3's panel is the editable plan; the core view stays |
| Stub planner | `agents/stubs/agents.py` `PlanGenerateStub` (priority 0) | Returns the canned contract example; stands down when Member 3's agent registers |
| Gold inputs | `samples/doc_intel/gold/expected/g01..g10.json` | 10 hand-labelled `RequirementSet`s (63 requirements) — reuse as planning inputs |
| TCP chat example (guide §32) | `samples/demo/tcp_chat_assignment.txt`, gold `g01_tcp_chat` | The golden scenario used again by Member 10 |

What Member 2 guarantees (HANDOFF, Sprint 2): every requirement has `id` R1.., `type`, `priority` must/should/could,
`source_ref` (with `folder` for multi-part uploads) and `confidence` (1.0 confirmed … 0.4 unverified);
`total_marks` only when it adds up; `open_questions` must be shown before approval; people may edit requirements
**after** the plan was made (newest version: `GET /api/doc_intel/requirements/{project_id}`).

---

## 1. Decisions (reviewed 2026-10-13 against Sprints 4–11)

The first draft's recommendations were checked against what later sprints need from the planner and executor:
- Sprint 4 (4.10/4.11) uses the M3 validators as programmatic critics and the M3 gold set in its ablation.
- Sprint 5 seeds research from `research_questions`.
- Sprint 7/8 run `code.implement` / `test.run` tasks. Sprint 8's sandbox limits concurrency through its own agent
  slots (8.11).
- Sprint 10 needs the coverage matrix (10.x inputs) and **"human change request mid-run → replan from that point,
  completed work preserved"** (10.17). Its recovery slot re-runs downstream tasks (10.7).
- Sprint 11 owns LLM request scheduling and concurrency (11.4) and benchmarks "M3 validity" (11.5).

Rule of thumb from that review: **every consumer reads `TaskGraph.tasks` as "the things that run"**. Keep that
true, keep core changes small and additive, and do not duplicate what a later member owns.

| # | Topic | Final decision | Changed? Why |
|---|---|---|---|
| D1 | Hierarchy (depth ≤ 3) | `TaskGraph.tasks` holds **only executable leaf tasks**. The hierarchy is *phase → group → task*: groups are `Roadmap.phases` entries with a new additive **`Phase.parent_id`** (M1, optional field), and a task belongs to its group through `Phase.task_ids` | **Changed.** Draft: group nodes as `PlanTask(kind="group")`. Those would be dispatched by the Manager and counted by M4/M10/M11 unless every one of them learned to skip them. Leaves-only needs no Manager change and no consumer change |
| D2 | Capability whitelist | Static list in the planner = the pipeline capabilities in `CAPABILITY_OUTPUTS` minus `document.extract` / `plan.generate` (`research.run, verify.claims, code.implement, test.run, docs.generate, review.final`). An optional `inputs["capabilities"]` narrows it. Enforced in the LLM schema (enum) **and** by the validator | **Changed.** Draft: a core change to read the registry. Stubs register every pipeline capability, so the registered set always contains this list; the core change bought nothing |
| D3 | Replanning while running | **(M1)** `Manager.replace_graph(project_id, graph, *, require_approval)`. Tasks whose plan id is kept and that are COMPLETED or in flight keep their task record. The other unfinished graph tasks are CANCELLED ("replanned"), and old ones get `TaskRecord.replaced = True` (jsonb, no migration). Reconcile and the outcome ignore replaced tasks. New tasks are inserted, the approval is re-gated, `graph_version` is bumped and the run outcome is reopened | **Kept, made precise.** Sprint 10's scenario 3 needs exactly this. Without `replaced`, the cancelled old tasks would make the project FAILED |
| D4 | Plan storage / versions | One `task-graph` artifact per project run. Each version (generated → human edit → replan) is a new **version of the same artifact id** (Member 2's pattern for requirement edits). **No migration** | Kept |
| D5 | Graph library | `networkx==3.6.1` (BSD). 3.7 needs Python ≥ 3.12 and the backend is 3.11 | Kept. The spec names it, and Member 9's import graphs can reuse it |
| D6 | Property tests | `hypothesis` (dev, MPL-2.0) | Kept |
| D7 | DAG UI | `@xyflow/react` 12 (MIT) for pan / zoom / drag-to-connect. Layout is **our own layered layout with barycenter ordering** in `logic.ts` (pure, unit-tested). No dagre | **Changed.** One dependency instead of two. The plan is ≤ 40 nodes, where a layered layout plus crossing reduction is enough; `elkjs` (EPL/GPL) stays out |
| D8 | Executor knobs | Only `HMAP_PLAN_MAX_PARALLEL` (running graph tasks per project, default 4) | **Changed.** Dropped `HMAP_PLAN_LLM_SERIAL`: LLM concurrency already lives in the gateway (`HMAP_LLM_MAX_CONCURRENCY`) and becomes Sprint 11's scheduler; the sandbox limit is Sprint 8's agent slots |
| D9 | Stub work time in demos | **(M1)** `HMAP_STUB_DELAY_S` (default 0), read by stub agents as a floor for their simulated work | **Changed.** Draft offered plan-supplied `inputs`. A model-written plan should not be able to set agent inputs; an env var for demos is enough |
| D10 | Priority | must → high, should → normal, could → low (a task takes its highest requirement); critical-path tasks +1 level (max urgent); the template's spine tasks are normal | Kept (marks weighting dropped: requirement ↔ criterion matching is fuzzy and would make priorities hard to explain) |
| D11 | Replan on failure | Member 3 serves `plan.replan` (capability + API + UI button). **Automatic** replanning after a failure is Member 10's recovery slot | Kept (matches 10.6/10.7/10.17) |
| D12 | Stale approvals | **(M1)** `approve(..., graph_version=None)`: a stale version → `StaleGraph` (API 409). The `approval.decided` event carries `graph_version`, so the planning plug-in can emit `plan.approved {project_id, plan_ref, graph_version}` | New |
| D13 | Core plan view after a replan | **(M1)** the dashboard's `stagesOf` / `PlanGraph` hide `replaced` tasks | New. Otherwise the core view shows old and new plan side by side |
| D14 | How the model is asked | One schema-constrained `reasoner` call **per part** (folder; a single part for one document), batched at ≤ 15 requirements. The template builds the spine (research → verify → design → implement → test → document → review). The model fills in implement / test / document detail, research questions, effort and extra dependencies. A rule planner produces a complete plan when there is no model or it fails | **Changed** from "one call per phase". Per part keeps cross-phase links (a test knows its implement task) visible to the model, needs 1–3 calls instead of 6 (local `qwen3.5:9b` ≈ 2.5 min per call), and each prompt stays far below Groq's 8K tokens/min per key |

---

## 2. Changes outside Member 3's folders (listed in the commit message)

1. **Dependencies:** `networkx==3.6.1`; dev `hypothesis`; frontend `@xyflow/react`.
2. **Contract (additive):** `Phase.parent_id: str | None` (D1). Snapshot re-accepted.
3. **`Manager.replace_graph` + `TaskRecord.replaced`** (D3), with core tests.
4. **`approve(graph_version=)` + `StaleGraph` + `graph_version` in `approval.decided`** (D12); core API passes it through.
5. **`HMAP_STUB_DELAY_S`** for stubs (D9); `.env.example` documents it and `HMAP_PLAN_MAX_PARALLEL`.
6. **Dashboard:** hide `replaced` tasks (D13); `Task.replaced` in `lib/types.ts`.
7. **Sprint-1/2 tests that assume the stub planner** (canned graph shape, task counts), updated like Member 2's request #6.
8. **`scripts/demo_sprint_3.sh` / `.py`** and `check_sprint.sh 3`.

---

## 3. Phases

### Phase A — Research and design (docs first)
`docs/members/3/research.md` — each topic with a short conclusion **and how it changes the code**:
- **HTN planning** (task → method → subtasks) vs **LLM decomposition**: Plan-and-Solve prompting, least-to-most,
  decomposed prompting, ADaPT (decompose only as needed), HuggingGPT/TaskBench-style task graphs.
- **Limits of LLM-only planning** (Kambhampati et al., "LLMs can't plan" / LLM-Modulo): cycles, missing deps,
  hallucinated tasks and agents → our "LLM proposes, code validates" design, with a measured example.
- **DAG theory:** topological order (Kahn), topological generations = parallel layers, critical path method
  (longest path with effort weights, slack), transitive reduction (drop redundant edges), cycle breaking
  (minimum feedback arc set heuristics).
- **Prioritisation:** MoSCoW, WSJF (cost of delay / job size), critical-path-first; which one we use and why (D10).
- **Roadmaps:** phases, milestones, parallel groups; effort estimation (heuristic per phase/capability, LLM estimate,
  PERT three-point) and their honesty limits.
- **Replanning:** plan repair vs replan from scratch; keeping completed work; minimal affected subgraph
  (descendants of the changed / failed node + tasks covering changed requirements).
- **Plan validation & metrics:** graph validity, coverage, node/edge F1 against reference plans (TaskBench-style),
  graph edit distance (why we don't use it as the main metric).
- **Executors:** layer-parallel vs ready-queue (list scheduling), concurrency caps, resource-aware scheduling.
- **Tools comparison:** networkx vs graphlib (stdlib `TopologicalSorter`) vs rustworkx; React Flow + dagre vs our own layered layout.

`docs/members/3/design.md`: the pipeline below, every module and its tests, data structures, prompt list with
versions and token budgets, failure modes and their fallbacks, the executor's behaviour table.

**Done when:** both docs exist; the design names every module, prompt and test; D1–D11 are settled.

### Phase B — Gold set and evaluation harness (before the planner, so every change is measured)
- `samples/planning/gold/`: ≥ 6 (target 8) cases, each `input.requirement_set.json` + `reference.task_graph.json`
  + `must_edges.json` (the "obvious" dependencies that every good plan must have):
  1. **TCP chat app** (guide §32, from `g01_tcp_chat`) — research → design → server/client → multi-client tests → docs → review
  2. DOCX lab manual (`g02`) — sequential steps
  3. rubric-heavy (`g03`) — marks-weighted priorities
  4. project brief with deliverables table (`g06`) — every deliverable produced by a task
  5. multi-part upload (`g08`, folders Part A/B/C) — one subtree per folder, cross-part deps only where stated
  6. typed request (`g09`) — tiny input, must not over-decompose
  7. long lab (`g10`, 31 requirements incl. lead-in lists) — size caps, grouping
  8. adversarial: low-confidence requirements, open questions, a requirement asking for an agent we don't have
     ("deploy to AWS") → flagged, not invented
- Reference plans are hand-written by us (no third-party text), reviewed by a second teammate if possible.
- `backend/tests/planning/eval/` (`metrics.py`, `run_eval.py`, modes `rules | replay | record | live`, same as Member 2):
  DAG validity % (before and after repair), coverage % (requirements, deliverables), flagged-uncovered count,
  task matching to the reference (requirement ids + phase + title similarity, one-to-one), **dependency
  precision / recall / F1** on matched tasks (edges compared after transitive closure, so A→B→C counts A→C),
  must-edge recall, invented-capability count (must be 0), depth / size limits, plan-generation latency and tokens.
- **Done when:** `uv run python -m tests.planning.eval.run_eval --mode rules` prints the table (the stub = baseline).

### Phase C — Skeleton, decomposition, dependencies (items 3.1–3.3)
- `templates/` + `skeleton.py` (3.1): phase templates per project type (software assignment, report/research,
  lab sheet, generic) → the spine research → design → implement → test → document → review, with the single
  final sink `review.final`. Folders (Part A/B/C) become sub-trees under implement/test. The LLM may only
  **adapt** the template (drop a phase that has no requirement, rename, add sub-phases), never remove the review sink.
- `decompose.py` (3.2): one schema-constrained `ctx.llm.generate(role="reasoner", schema=...)` call **per part** (D14)
  (≤ 15 requirements per call; temperature 0, seed; prompt versioned → replay cache valid). Input: the part's requirements
  (id + text + priority), constraints, deliverables, allowed capabilities. Output per task: title, description,
  `agent_capability` (enum of allowed ones), `requirement_ids`, `acceptance_criteria` (testable, derived from the
  requirement text and rubric), `research_questions` for `research.run` tasks (Member 5's seed), effort estimate.
  Limits: depth ≤ 3, ≤ 8 children per node, ≤ `HMAP_PLAN_MAX_TASKS` (default 40) leaves; over-fine output is merged.
  Repair: schema repair (gateway), unknown requirement ids dropped, unknown capability → nearest allowed by phase
  (or flagged), then one targeted re-ask; then **rule fallback** (requirements grouped by section, one implement task per group, spine from the template) so a plan is
  always produced, and the plan says so.
- `dependencies.py` (3.3): three sources, merged and deduplicated —
  (a) **rule edges** from phase order (design → implement → test → document → review; research before what it informs);
  (b) **data-flow edges** from artifacts: a task that needs `code-change-set` depends on the task producing it
  (`CAPABILITY_OUTPUTS`), tests depend on the code they test, docs on code + test report, review on everything;
  (c) **LLM edges** proposed in the decomposition answer, kept only if they reference real tasks and don't create cycles.
  Then **transitive reduction** so the drawn graph stays readable.
- Constraints (technology / format / process) are attached to the acceptance criteria of the tasks they affect;
  deliverables map to the task that produces them (deliverable coverage).
- **Done when:** gold plans are valid, cover all requirements, must-edge recall ≥ 0.9; unit tests pass.

### Phase D — Validator, scheduler, coverage, roadmap (items 3.4–3.7)
- `validate.py` (3.4): networkx checks + **auto-repair**, each repair logged in the plan's notes:
  cycles (break the lowest-confidence LLM edge first, never a rule edge), orphans (attach to their phase's
  predecessor), multiple sinks (connect to the final review), unknown capabilities, empty acceptance criteria,
  tasks justified by no requirement / deliverable / template (flag or drop), depth/size caps, duplicate titles.
  Exposed as `validate_plan(graph, requirement_set) -> list[Issue]` — **a stable function Member 4 uses as a
  programmatic critic** (Sprint 4 item 4.10).
- `schedule.py` (3.5): topological generations (parallel layers), critical path (effort-weighted longest path,
  slack per task), priority score (D10). **Deterministic**: ties broken by task id; same input → same output.
- `coverage.py` (3.6): requirement → task ids (and deliverable → task ids); "uncovered" report: every requirement
  is covered **or explicitly flagged** with a reason (out of scope, needs a human, unclear → linked open question);
  low-confidence requirements (< 0.7) and Member 2's `open_questions` are carried into the plan as questions to
  answer at approval.
- `roadmap.py` (3.7): phases, milestones (end of each phase + one per folder/part + each deliverable), parallel
  groups, effort per phase and total, critical path; `Roadmap.markdown` for humans and JSON for the UI.
- **Done when:** property tests (random DAGs and random cyclic graphs: repair always yields a valid single-sink DAG
  that keeps every task) pass; schedule tests are deterministic; coverage report is 100 % covered-or-flagged on gold.

### Phase E — Agent, executor, replanning, API (items 3.8–3.11)
- `agent.py` (3.8): `PlanningAgent(BaseAgent)` for `plan.generate` and `plan.replan`, priority 100 (stub stands
  down). Reads the `requirement-set` ref (`artifact_type == "requirement-set"`, `ctx.get_json(ref, RequirementSet)`);
  ignores the `document-model` except for folder names. Progress ("Planning phase 3 of 6"). Returns the
  `task-graph` artifact (and a `plan-report` artifact: issues, repairs, flags, model used, prompt version).
  **Idempotent**: same RequirementSet + prompt version → cached result, no second LLM call on redelivery.
  Honours cancellation and `cloud_ok` (via `ctx.llm` only).
- `executor.py` (3.9): `LayerParallelExecutor` implementing `GraphExecutor`:
  `order` = layers then priority; `ready` = dependencies COMPLETED, approved, **capped** by
  `HMAP_PLAN_MAX_PARALLEL` running tasks per project (D8); `blocked` = transitive propagation with the blocking reason; `outcome` same semantics as the naive one.
  Registered with `provides={"executor": LayerParallelExecutor()}`; with `HMAP_PLUGINS` excluding `planning`
  the naive executor still runs (test).
- `replan.py` (3.10): inputs = current graph + task states + human feedback ("don't use X", "split T4") or a failed
  task id. Affected subgraph = changed/failed nodes + descendants + tasks covering changed requirements; completed
  tasks are **kept verbatim** (same plan ids), only the affected part is regenerated (same decomposer, smaller
  prompt) and revalidated; new version → `replace_graph` (D3) → approval again.
  Also offered when the RequirementSet changed after planning (Member 2's edits don't replan automatically).
- `hooks` in `plugin.py`: on `approval.decided` with `approved=True` emit **`plan.approved {project_id, plan_ref,
  graph_version}`** (declared in Sprint 1, emitted by nobody yet). No hooks for upload / extract / submit (pipeline owns those).
- `router.py` (3.11), mounted at `/api/planning/…`, every route checks `owned_project`, CSRF on writes:
  `GET /plan/{project_id}` (latest or `?version=`, with issues / coverage / schedule), `GET /plan/{project_id}/versions`,
  `PUT /plan/{project_id}` (human edit with `base_version`; revalidated; invalid → 422 with the issues; stale → 409),
  `POST /plan/{project_id}/approve` (thin wrapper over the core approval with `graph_version`, comment required on reject),
  `POST /plan/{project_id}/replan` (feedback text and/or failed task id), `GET /plan/{project_id}/roadmap.md`.
- **Done when:** upload → requirements → plan → approval → stubs run in dependency order, on the in-memory bus
  **and** on RabbitMQ + Postgres; redelivery does no second LLM call.

### Phase F — UI panel (item 3.12)
`frontend/src/features/planning/` (`defineFeature({ id: "planning", title: "Plan", ProjectPanel, order: 20 })`):
- **DAG view** (React Flow + our own layered layout, D7): nodes coloured by phase, badges for capability / priority / critical path,
  live state from the event stream once running; parallel layers visible; groups collapsible (D1).
- **Edit:** task fields (title, description, capability from the allowed list, acceptance criteria, requirement
  links), add / remove task, add / remove edge (drag), all revalidated by the server before saving as a new version;
  validation issues shown inline. Undo before save.
- **Roadmap view** (phases, milestones, effort, critical path), **coverage matrix** (requirements × tasks, uncovered
  and flagged rows highlighted, click → task / source requirement), Member 2's **open questions** and low-confidence
  requirements shown before approval.
- **Approve / reject with comment**, **Replan** with feedback text, version history with diff, "requirements changed
  since this plan" banner. Works in auto-approve projects (edit → replan path).
- Simple vs Developer mode (dev: model, prompt version, repairs, raw JSON); light/dark tokens; phone width (375 px)
  without sideways scrolling; keyboard accessible (React Flow's a11y options).
- Tests: `logic.ts` pure functions (graph diff, validation display, coverage grouping, critical-path highlight) in
  `logic.test.ts`; a DOM test for the approve/edit flow if cheap (Member 2 had none — a known gap worth closing).
- **Done when:** lint, typecheck, tests, build pass; checked by hand in the browser with screenshots.

### Phase G — Evaluation, tests, demo, handoff (items 3.13–3.15, DoD)
- Record the replay cache on the gold set (`--mode record`, cloud) into `samples/llm_cache/planning/`; one
  local-only run (`--mode live --local-only`, never `record`) for the cloud-vs-local comparison; rules-only baseline.
- `docs/members/3/eval.md`: validity % (before/after repair), coverage %, dependency P/R/F1, must-edge recall,
  invented capabilities, latency, tokens; ablations (rules-only vs LLM vs hybrid deps; with/without transitive
  reduction; per-phase vs one-shot decomposition); honest limitations.
- Tests `backend/tests/planning/` (3.15): templates; decomposition parsing + repair + fallback (FakeLLM);
  dependency rules; validator **property tests** (hypothesis); schedule determinism; coverage; roadmap markdown;
  replan keeps completed tasks; executor **concurrency** (two independent tasks overlap; cap respected; BLOCKED
  propagation; naive fallback without the plug-in); agent idempotency; API (ownership 404, CSRF, versions, 409, 422);
  JSON-Schema validation of every gold output against `TaskGraph.schema.json`; contract test M2 → M3 on Member 2's
  real gold outputs; **integration** RequirementSet → approved plan → stub execution over RabbitMQ + Postgres; the
  full Sprint 1 + 2 suite unchanged.
- `scripts/demo_sprint_3.sh` (M1 path, D9): PDF → requirements → plan → approve → stubs execute in dependency order,
  with the event log proving two tasks overlapped; replay mode, no keys or Ollama; `--live` for real models.
- Docs: `docs/members/3/{README, research, design, eval, testing}.md`, `samples/planning/README.md`;
  `HANDOFF.md` section for Member 4 (below).
- **Done when:** `scripts/check_sprint.sh 3` passes; Docker / Ollama stopped; handoff note written.

---

## 4. Definition of Done (spec §8 + project rules)
- [ ] Every generated plan on the gold set is acyclic and single-sink; 100 % of requirements covered or explicitly flagged
- [ ] No invented capability in any plan (whitelist enforced, tested)
- [ ] Parallel execution demonstrated: two independent tasks overlap in time in the event log
- [ ] Human approve + edit + replan works from the UI (screenshots in `testing.md`)
- [ ] Replan keeps completed tasks (test + demo)
- [ ] `demo_sprint_3.sh`: PDF → plan → approve → stubs execute in dependency order (memory and RabbitMQ + Postgres)
- [ ] Without the planning plug-in the naive executor still runs everything (test)
- [ ] Replay cache recorded; tests and demo need no network, keys or Ollama
- [ ] `scripts/precommit.sh --member 3 --base <Sprint-2 handoff>` clean (ownership, secrets, lint, types, tests)
- [ ] `scripts/check_sprint.sh 3` PASS; no key in any committed file, log or recording

## 5. Interface handed on (spec §7 + what later sprints read)
- **Artifact** `task-graph` (`TaskGraph`) — each task: `id, title, agent_capability, requirement_ids[],
  acceptance_criteria[], depends_on[], priority, phase` (leaves only; the hierarchy is `roadmap.phases` with `parent_id`, D1); `research_questions`
  on every `research.run` task (**Member 5**); `coverage_matrix`; `roadmap` with markdown.
- **Event** `plan.approved {project_id, plan_ref, graph_version}`.
- **`validate_plan()` / `coverage()`** as importable functions for **Member 4**'s critics (Sprint 4 §4.10/4.11)
  and the M3 gold set + harness for Member 4's ablation and **Member 11**'s benchmark ("M3 validity").
- **`plan.replan`** capability for **Member 10**'s recovery planner (revise / rerun / replan / ask human).
- Executor behaviour documented for every member: tasks get their dependencies' artifacts
  (`inputs.dependency_artifacts`), their requirement ids and phase.

## 6. Order and rough effort

| Order | Phase | Effort |
|---|---|---|
| 1 | Settle D1–D11; Member-1 requests (deps, contract fields, capabilities input, `replace_graph`, stub delay, test updates) | medium |
| 2 | A research + design | medium |
| 3 | B gold set (8 cases) + eval harness | medium |
| 4 | C skeleton, decomposition, dependencies | large |
| 5 | D validator (+ property tests), scheduler, coverage, roadmap | medium–large |
| 6 | E agent, executor, replan, hooks, API | large |
| 7 | F UI panel (React Flow) | large |
| 8 | G recording, eval, demo, docs, `check_sprint.sh 3` | medium |

## 7. Risks

| Risk | Mitigation |
|---|---|
| LLM invents tasks or agents | Capability enum in the schema + whitelist; every task must cite a requirement / deliverable / template; validator drops or flags the rest |
| Cycles / missing deps from the model | Code builds the spine and data-flow edges; LLM edges are optional extras; repair + must-edge eval |
| Over-fine or huge plans (31-requirement lab) | Depth ≤ 3, ≤ 8 children, ≤ 40 leaves, merge step; grouping by phase / folder |
| Planner / executor / Manager mismatch | Only the shared `TaskGraph` contract; contract + JSON-Schema tests; integration test on the real stack |
| Replan destroys finished work | `replace_graph` keeps completed tasks; dedicated test; fallback: replan only before execution |
| Groq 8K tokens/min, Gemini daily quota (hit in Sprint 2) | Per-phase prompts (small); key pool fallback; recorded answers for tests and demo; re-record when quota resets |
| Local model slow (≈ 2.5 min per call on the demo laptop) | Per-phase calls run sequentially; rules fallback; cloud default; latency reported honestly |
| Prompt injection via document text into plan prompts | Requirements are data in the prompt; outputs are schema-validated and whitelisted; nothing in a plan is executed by the planner |
| Edits to requirements after planning go unnoticed | Version check + banner + one-click replan |
| Auto-approve projects start before a human looks | Plan still editable; edits go through replan; Stop button already exists |
| Sprint 1/2 regressions (stub planner assumptions in tests) | M1 request #7; `make precommit` after every phase |
