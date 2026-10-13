# Member 3 — Planning and task decomposition

A `RequirementSet` becomes a validated, traceable plan: a DAG of steps (research → verify → design → build / test
per part → documents → final review) with dependencies, priorities, the agent for each step, acceptance criteria,
a roadmap and a requirement ↔ step coverage matrix. A person approves, edits or changes it; a layer-parallel executor
runs it, and replanning keeps the work that is already done.

| | |
|---|---|
| Plug-in | `backend/src/hmap/agents/planning/` (priority 100; replaces the `plan.generate` stub and the Manager's naive executor) |
| Capabilities | `plan.generate` → `task-graph` (`TaskGraph`) + `plan-report`; `plan.replan` → the next version of the same `task-graph` |
| Inputs | the `requirement-set` artifact (+ `document-model` for section names); optional `inputs["capabilities"]`; replan: `feedback`, `failed`, `states` |
| Strategy slot | `executor` = `LayerParallelExecutor` (`HMAP_PLAN_MAX_PARALLEL`, default 4) |
| Events | `plan.approved {project_id, plan_ref, graph_version, auto}` |
| UI panel | `frontend/src/features/planning/` (project tab "Plan": graph, steps, roadmap, coverage, versions) |
| API | `GET/PUT /api/planning/plan/{project_id}`, `POST …/approve`, `POST …/replan`, `GET …/roadmap.md`, `GET /api/planning/capabilities` |
| For later members | `validate.validate_plan()` / `coverage.coverage()` (Member 4's critics), the gold set + harness (Members 4, 11), `research_questions` (Member 5), `plan.replan` + `Manager.replace_graph` (Member 10) |
| Docs | [plan](plan.md) · [research](research.md) · [design](design.md) · [eval](eval.md) · [testing](testing.md) |

## Run
```bash
cd backend && uv run pytest tests/planning -q                        # unit, property, replay, API (+ integration with infra up)
uv run python -m tests.planning.eval.run_eval --mode replay          # scores on the gold set, no network
uv run python -m tests.planning.eval.run_eval --mode record          # live models (cloud first), re-records answers
uv run python -m tests.planning.eval.run_eval --mode live --local-only   # local qwen3.5:9b, never recorded
uv run python -m tests.planning.eval.run_eval --mode record --replans-only   # re-record only the 2 replan scenarios
uv run python ../samples/planning/gold/build_inputs.py               # regenerate the planner inputs from Member 2's gold
cd .. && scripts/demo_sprint_3.sh                                    # demo (replay; add --live for real models)
```

## Limitations
- Recorded answers come from Groq `gpt-oss-120b` (Gemini answered 503 on the recording day). Two replanning
  scenarios are recorded; the demo's own replan is not, so replay demos change that plan with the rules (feedback
  becomes acceptance criteria or a change-request step).
- Effort estimates are rough (heuristics + the model's guess, clamped 0.5–16 h); they order work, they are not
  promises.
- Requirements a person must do are recognised by phrases (demo in person, upload to the portal, present the demo);
  anything else that no agent can do relies on the model's `not_plannable`.
- A requirement edit in the Requirements tab does not replan by itself: the Plan tab shows "requirements were
  edited" with a one-click "Update the plan".
- Automatic replanning after a failed step is Member 10's (recovery slot); here a person starts it ("Change plan…"
  sends the failed steps along).
- The gold set and reference plans are ours and were used while tuning the prompt; granularity is a judgement call.
