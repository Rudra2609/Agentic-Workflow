# Sprint 3 — Member 3: Planning & Task Decomposition

**Owner:** Member 3 · **Needs:** Sprint 2 accepted · **Unblocks:** Sprint 4/5 (real tasks to run)
**Replaces stub:** `plan.generate` → `agents/planning/`; provides the DAG executor through the plug-in `executor` slot (no `manager/` edit).

## 1. Goal
Convert a `RequirementSet` into a **validated hierarchical task graph (DAG)** with dependencies, priorities, agent-capability assignment, acceptance criteria, a roadmap, and a **requirement↔task coverage matrix** — with a **human approval gate**.

## 2. Provided by earlier sprints
S1: Manager executor (naive), approval-gate states, registry capabilities list, `TaskGraph` contract. S2: `RequirementSet` artifacts + `project.requirements_ready` event.

## 3. Research deliverable
Hierarchical task networks (HTN) & LLM planning (e.g., decomposition prompting, plan-and-solve), DAG theory (topological order, critical path, layers), prioritization (MoSCoW, WSJF, critical-path-first), roadmap/phase generation, replanning, plan validation; limitations of LLM-only planning (cycles, missing deps, hallucinated tasks).

## 4. Design

```text
RequirementSet
  → [Phase skeleton] template library (research/design/implement/test/docs/review) + LLM adaptation
  → [Decomposer] LLM(schema) per phase → tasks → subtasks (depth ≤ 3), each with agent_capability + acceptance_criteria
  → [Dependency inference] rule edges (design→impl→test→docs→review) + LLM edges + data-flow edges (artifact in/out)
  → [Validator] DAG check (networkx): no cycles, no orphans, single sink "final review", every req covered, every task justified
  → [Scheduler] topological layers, critical path, priority score
  → [Roadmap] phases/milestones, parallel groups
  → TaskGraph artifact → HUMAN GATE → Manager executes
```
Capability assignment is restricted to capabilities **actually registered** (query registry) — prevents inventing agents.

## 5. Work items

### MUST
| # | Item | Files (`agents/planning/`) | Acceptance |
|---|---|---|---|
| 3.1 | Phase templates + LLM skeleton | `skeleton.py`, `templates/` | every plan has research→…→review spine |
| 3.2 | LLM decomposition (constrained schema), depth/branching limits | `decompose.py` | valid `TaskGraph` ≥ 95 % w/ repair |
| 3.3 | Dependency inference (rules + LLM + artifact data-flow) | `dependencies.py` | no missing obvious deps on gold plans |
| 3.4 | DAG validator & auto-repair (cycle breaking, orphan attach) using networkx | `validate.py` | property tests on random graphs |
| 3.5 | Prioritization + critical path + parallel layers | `schedule.py` | deterministic; unit-tested |
| 3.6 | Coverage matrix + traceability (task ↔ requirement ids) and “uncovered requirement” report | `coverage.py` | 100 % reqs covered or flagged |
| 3.7 | Roadmap generation (phases, milestones, effort estimates) | `roadmap.py` | JSON + markdown |
| 3.8 | `PlanningAgent` capability `plan.generate` (+ `plan.replan`); return the plan as an artifact of type `task-graph` — Member 1's `pipeline` plug-in then submits it to the Manager for approval automatically (no extra hook needed) | `agent.py` | on bus; idempotent |
| 3.9 | Manager integration: provide a **layer-parallel DAG executor** (plug-in strategy slot `executor`, replaces M1's naive one) respecting deps, concurrency caps, `BLOCKED` propagation; **approval gate** before execution | `executor.py`, registered in `plugin.py` | parallel tasks run concurrently; blocked ones wait; `HMAP_PLUGINS` without planning falls back to the naive executor |
| 3.10 | **Replanning**: given human feedback (“don’t use X”) or failed task → regenerate affected subgraph only, keep completed work | `replan.py` | completed tasks preserved |
| 3.11 | API: `GET/PUT /projects/{id}/plan`, `POST …/approve`, `POST …/replan` | `router.py` (auto-mounted via `plugin.py`) | versioned plans |
| 3.12 | UI: **React Flow DAG**, roadmap view, coverage matrix, edit task/edge, approve/reject w/ comment | `frontend/src/features/planning/` | human edit → revalidated |
| 3.13 | Gold set: ≥6 RequirementSets (incl. TCP chat example from guide §32) with reference plans | `samples/planning/` | for eval |
| 3.14 | Eval: DAG validity %, coverage %, dependency precision/recall vs reference, plan-gen latency | `tests/planning/eval/` | `eval.md` |
| 3.15 | Tests: validator properties, executor concurrency, integration (RequirementSet→approved plan→stub execution) | `tests/planning/` | green |

### STRETCH
Effort/duration estimation from history; resource-aware scheduling (single GPU ⇒ serialize LLM-heavy tasks); alternative plan proposals ranked.

## 6. Local-LLM notes
`role="reasoner"`; decomposition per phase (small prompts); LLM proposes, **code validates** — never trust the model's graph; use rule templates to anchor structure.

## 7. Interface handed to Member 4/5 and Manager
```text
Artifact: TaskGraph.json   Event: plan.approved {project_id, plan_ref}
Each task: id, title, agent_capability, requirement_ids[], acceptance_criteria[], depends_on[], priority, phase
Manager creates executions per ready task; research tasks carry a ResearchBrief seed (questions) for M5.
```

## 8. Definition of Done (additions)
- [ ] All generated plans on gold set are acyclic, 100 % covered or explicitly flagged
- [ ] Parallel execution demonstrated (two independent tasks overlap in time in the event log)
- [ ] Human approval + edit + replan demo works from UI
- [ ] Demo `demo_sprint_3.sh`: PDF → plan → approve → stubs execute in dependency order

## 9. Risks
LLM invents tasks/agents → capability whitelist + validator; over-fine decomposition → depth/size caps; planner/executor mismatch → shared `TaskGraph` contract tests.
