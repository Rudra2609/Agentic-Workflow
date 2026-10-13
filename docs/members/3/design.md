# Design — Member 3: planning and task decomposition

Decisions and why: [plan.md §1](plan.md). Background: [research.md](research.md).

## 1. Pipeline (`backend/src/hmap/agents/planning/`)

```text
RequirementSet (+ Member 2's document-model for section names)
  -> skeleton.py     project kind (software | document), parts = upload folders, spine from templates.py
                     (research -> verify -> design ... review), human-only requirements flagged, questions collected
  -> decompose.py    per part, <= 15 requirements per call: one schema-constrained `reasoner` call (DraftPlan:
                     build / test steps, research questions, not-plannable, open questions); the rule planner when
                     there is no model, it fails, or it answers nothing; ids T1.., groups, model edges
                     + every requirement of the part in some step; a document step per document deliverable
  -> dependencies.py template (design -> builds), data-flow (builds -> tests -> documents; research -> verify),
                     rule (Part B names Part A -> B's builds after A's); model edges kept
  -> pipeline.finalize:
       validate.repair   unknown deps / ids / capabilities, criteria, cycles (least trusted edge first),
                         duplicate titles, size cap (merge), orphans, single sink (the final review)
       validate.check    hard errors left -> refused (only possible for human edits)
       validate.reduce   transitive reduction
       schedule.py       layers, critical path, slack, priorities (MoSCoW + critical path), execution order
       coverage.py       requirement -> steps; covered / flagged / missing
       roadmap.py        hierarchy (Phase.parent_id; a group with > 8 direct steps is split while depth < 3),
                         milestones, Markdown
  -> TaskGraph (artifact `task-graph`) + PlanReport (artifact `<graph id>-report`)
```

`replan.py` (new version after feedback / failures / changed requirements) and `replan.apply_edit` (a person's
version) go through the same `finalize`, so every version passes the same checks.

## 2. Data

| Thing | Where | Notes |
|---|---|---|
| `TaskGraph` | shared contract | `tasks` = executable leaves only; `roadmap.phases` = groups with `parent_id` (≤ 3 levels: phase → part → feature group); `coverage_matrix` = requirement → build / test / document steps (the review does not count) |
| `PlanReport` | `agents/planning/model.py`, artifact `plan-report` | origin (generated / edited / replanned), method (llm / rules / mixed), model calls + who answered, fallbacks, repairs, warnings, flagged requirements, deliverable → steps, questions, edge sources, schedule, feedback, author |
| Versions | artifact versions | one `task-graph` artifact per run; an edit or replan adds a version of the same artifact id; `TaskGraph.version` = artifact version = the Manager's `graph_version` |
| Ids | | spine steps: `research`, `verify`, `design`, `review`; others `T1..`; a re-run finisher after a replan: `review-v3` |

## 3. The model call

- `role="reasoner"`, temperature 0, seed 7, `max_tokens` 4000, schema `DraftPlan` (nulls become defaults).
  Prompt version **2** (`PROMPT_VERSION`): v2 added "few steps", "writing tests is a build step" and the dependency
  guidance after v1 over-split writing work and missed "tests after the code they test".
- Spec 3.1 says "phase templates + LLM skeleton". The spine is deliberately *not* model-adapted: every plan must
  have research → … → review (the acceptance), and a model allowed to drop or rename phases would only add a way to
  break it. The model adapts *inside* the spine instead: the steps per part, their feature groups (the third
  hierarchy level), the research questions, and what is not plannable.
- Input per call: the part's requirements (`R3 [must, functional] text (section: …)`), all constraints, the kind.
  Never the spine, never ids to invent, never capabilities outside the whitelist (code assigns them by phase).
- Prompt sizes on the gold set: 1.1–1.6 K input tokens, ≤ 2 K output — well inside Groq's 8 K tokens / min per key and
  the local 8 K context.
- Replanning: `ReplanDraft` (remove / change / add / notes) with the plan listed and finished steps marked
  "do not touch"; the code ignores any attempt to touch them.
- Caching: answers cached by prompt hash in the agent's memory (redelivery → no second call); the gateway's replay
  cache (`samples/llm_cache/planning/`) makes tests and demos offline.

## 4. Failure modes

| Failure | Behaviour |
|---|---|
| No model / no keys / local-only project | rule planner (same shape), `method = rules` |
| Model error, invalid JSON after repairs, empty answer | rules for that part, `fallbacks` names the part and reason |
| Unknown requirement id / capability, missing criteria | dropped / mapped by phase / derived from the requirements; logged in `repairs` |
| Requirement missed by the model | joins the build step with most words in common (≥ 25 %), else rule-made steps |
| Cycle | the least trusted edge of the cycle is removed until acyclic |
| Too many steps (> 40) | test steps, then build steps of the same group are merged pairwise |
| Requirement only a person can do (demo in person, upload to the portal) | flagged with a reason, shown before approval, not planned |
| Human edit with a cycle / unknown capability / changed finished step | 422 with the problems; nothing saved |
| Approval of a replaced version | 409 (`StaleGraph`) |
| Feedback after every step finished | a change-request build + test step; documents and review run again |
| No model during a replan | feedback becomes acceptance criteria on unfinished steps ("Do not use X" + the full feedback) |

## 5. Executor (`executor.py`, plug-in slot `executor`)

| Method | Behaviour |
|---|---|
| `order` | layer by layer; inside a layer urgent → low, then id |
| `ready` | approved, every dependency COMPLETED (naive semantics), and at most `HMAP_PLAN_MAX_PARALLEL` plan steps of the project in flight (READY … REVIEWING); most urgent first. Non-plan tasks (extract, plan, replan) are never capped |
| `blocked` | inherited: dependants of failed / cancelled / blocked steps become BLOCKED, transitively |
| `outcome` | inherited; the Manager hides `replaced` steps from it |

Without the planning plug-in (`HMAP_PLUGINS` without `planning`) the Manager keeps the naive executor.

## 6. API (`/api/planning`, owner only, CSRF on writes)

| Route | Notes |
|---|---|
| `GET /plan/{project}` `?version=` | graph, report, versions, `submitted_version`, step states (current run), requirements changed? |
| `PUT /plan/{project}` | `{artifact_id, base_version, graph}` → 409 stale, 422 `{message, issues}`, else next version + `replace_graph` |
| `POST /plan/{project}/approve` | `{approved, graph_version, comment}`; rejecting needs a comment |
| `POST /plan/{project}/replan` | `{feedback, failed}` → a `plan.replan` task (202); its result replaces the plan via the hook |
| `GET /plan/{project}/roadmap.md` | Markdown download |
| `GET /capabilities` | whitelist and the capabilities allowed per phase |

Hooks: `task.completed` (plan.replan) → `replace_graph`; `approval.decided` (approved) → `plan.approved
{project_id, plan_ref, graph_version, auto}`.

## 7. UI (`frontend/src/features/planning/`, tab "Plan")

Graph (React Flow; layered layout with barycenter crossing reduction in `logic.ts`; a wide plan opens at its first
steps at a readable zoom), Steps table, Roadmap (groups, milestones, critical path, stages), Coverage matrix,
Versions (diff between versions). Approve / Reject (comment) / Edit (add, remove, change steps; drag to connect,
click to disconnect; loops refused before saving) / Change plan (feedback; failed steps are sent along). Banners:
requirements edited after planning, failed steps, questions before approval, things only a person can do.
Developer mode: method, model, fallbacks, edge sources, repairs, raw JSON. Live step states from the event stream.
