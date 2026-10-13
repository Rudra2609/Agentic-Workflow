# Testing — Member 3: planning and task decomposition

What is tested, how to run it, and what each test proves. Scores on the gold set are in [eval.md](eval.md).

## 1. How to run
```bash
cd backend
uv run pytest tests/planning -q                       # Member 3's backend tests (integration skips without infra)
make infra-up && uv run pytest tests/planning -q      # ... including the RabbitMQ + Postgres test
uv run pytest tests/manager/test_replace_graph.py -q  # the Manager's replanning (made for Sprint 3)
cd ../frontend && npm test -- src/features/planning   # the Plan panel's logic
cd .. && scripts/demo_sprint_3.sh                     # the scripted demo (in memory, replay mode)
scripts/check_sprint.sh 3                             # everything: secrets, lint, types, all tests, build, demo
```
Nothing needs a network, an API key or Ollama: the model's answers are replayed from `samples/llm_cache/planning/`
or scripted with `FakeLLM`.

| What | Count | Where |
|---|---|---|
| Backend tests (Member 3) | 57 (incl. 9 JSON-Schema cases, 2 recorded replans, 1 property test with 150 random graphs, 1 integration) | `backend/tests/planning/` |
| Manager tests made for Sprint 3 | 4 | `backend/tests/manager/test_replace_graph.py` |
| Frontend tests | 15 (10 logic + 5 DOM) | `frontend/src/features/planning/logic.test.ts`, `PlanPanel.test.tsx` |

## 2. Test data
- **Gold inputs** (`samples/planning/gold/inputs/`): Member 2's real outputs on 7 of Member 2's gold documents
  (made in replay mode by `build_inputs.py`) plus 2 hand-written requirement sets (things only a person can do;
  a writing project). **Reference plans** and must-have dependencies: `samples/planning/gold/references.py`.
- **Recorded answers** (`samples/llm_cache/planning/`): 13 cloud answers (Groq `gpt-oss-120b`): 11 plans (prompt v2)
  and 2 replans. The key
  covers the prompt, so a prompt or input change needs a re-record:
  `uv run python -m tests.planning.eval.run_eval --mode record` (team keys in `.env`).

## 3. What each file covers

### `test_decompose.py` — skeleton (3.1), decomposition (3.2), dependencies (3.3)
| Test | Proves |
|---|---|
| `test_whitelist_never_contains_the_planning_steps_themselves` | a plan can only use the six pipeline capabilities (never `plan.*` or `document.extract`) |
| `test_project_kind` | software vs writing projects; ties go to software |
| `test_skeleton_is_the_spine_with_review_criteria` | research → verify → design … review; the review checks every constraint, deliverable and the marking scheme |
| `test_parts_follow_upload_folders_and_sections` | one part per folder (Part A/B/C), "General" for loose requirements, section names from the document model |
| `test_things_only_a_person_can_do_are_flagged` | live demo, upload to Moodle, "present the demo" flagged; "attendees" / "download" are not; low-confidence requirements become questions |
| `test_rule_draft_groups_and_tests_every_build_step` | the rule planner: build steps of ≤ 3 related requirements, one test per build, quality requirements in tests |
| `test_prompt_lists_requirements_constraints_and_part` | the prompt holds only this part's requirements, the constraints, the rules |
| `test_model_plan_is_cleaned_and_whitelisted` | unknown ids dropped, invented capability mapped, effort clamped, missing criteria derived, research questions reach the research step, temperature 0 / `reasoner` |
| `test_model_failure_or_empty_answer_falls_back_to_rules_and_says_so` | a failing or empty model still gives a fully covering plan; `fallbacks` says why |
| `test_cache_means_no_second_model_call` | same input → cached answer, one model call |
| `test_dependencies_from_templates_dataflow_and_parts` | Part B after Part A ("use the schema from Part A"), Part C tests after Part B, every test after a build, one sink |
| `test_priorities_follow_moscow_and_the_critical_path` | critical steps with requirements are high / urgent |

### `test_validate_schedule.py` — validator (3.4), schedule (3.5), coverage (3.6), roadmap (3.7)
| Test | Proves |
|---|---|
| `test_check_reports_every_kind_of_problem` | cycle, unknown dependency, self dependency, invented / planning capability, no criteria, several sinks, sink not a review, unknown / uncovered requirement, duplicate id, unjustified and orphan warnings |
| `test_repair_fixes_a_broken_model_plan` | a broken plan becomes valid; the model's backward edge is what breaks the cycle |
| `test_repair_always_yields_a_valid_single_sink_dag_and_keeps_every_task` | **property test** (150 random, possibly cyclic graphs): repair always gives an acyclic plan ending in one review, keeps every task; transitive reduction keeps reachability |
| `test_schedule_layers_critical_path_and_slack` | layers, critical path, makespan, slack, earliest start; order-independent |
| `test_priorities_do_not_creep_up_over_versions` | re-finalising a plan does not raise priorities again |
| `test_coverage_matrix_and_roadmap_on_the_gold_plans` | 100 % covered or flagged, hierarchy ≤ 3 levels with every task in one group, milestones per part, Markdown sections |
| `test_roadmap_handles_an_empty_requirement_set` | edge case |

### `test_pipeline.py` — the whole planner on the gold set
| Test | Proves |
|---|---|
| `test_gold_set_in_replay_meets_the_sprint_targets` | **the Sprint-3 targets** on the recorded answers: every plan valid, 100 % covered or flagged, no invented capability, flags exactly right, must-have dependencies ≥ 90 % |
| `test_the_recorded_answers_are_used` | replay really uses the recorded model answer |
| `test_output_validates_against_the_exported_json_schema[9 cases]` | each output passes `TaskGraph.schema.json` (what the Manager and other members read) and round-trips |
| `test_replay_is_deterministic` | same input → same plan and schedule |
| `test_rules_alone_also_meet_validity_and_coverage` | no model at all still meets validity and coverage |
| `test_every_research_step_carries_questions_for_member_5` | research steps carry research questions |
| `test_progress_and_cancellation` | progress only goes up and names the part; cancelling stops the run |
| `test_recorded_replans_keep_finished_work_and_follow_the_feedback[tcp_chat, long_lab]` | the model's recorded replans: finished steps untouched, valid, covered, and the asked change happened (asyncio; one CLI step) |

### `test_executor.py` — the layer-parallel executor (3.9) in the Manager
| Test | Proves |
|---|---|
| `test_the_plugin_provides_the_executor_and_the_naive_one_stays_the_default` | the slot is filled by the plug-in; without it the naive executor stays |
| `test_order_is_layer_by_layer_most_urgent_first` | creation order |
| `test_independent_steps_run_at_the_same_time` | three independent steps assigned together and RUNNING at the same time, the urgent one first |
| `test_the_cap_limits_running_steps_per_project` | cap 2: the third waits in CREATED and starts when a slot frees |
| `test_failed_step_blocks_its_dependants_only` | BLOCKED propagation, project FAILED |
| `test_pipeline_steps_are_never_capped` | non-plan tasks are not held back |

### `test_replan.py` — replanning (3.10) and edits (3.12)
| Test | Proves |
|---|---|
| `test_rule_replan_keeps_finished_steps_and_adds_the_feedback` | finished / running steps unchanged; "Do not use threads" on every unfinished build / test step |
| `test_model_replan_cannot_touch_frozen_steps` | the model's remove / change of a finished step is ignored; its new step is added and connected |
| `test_model_failure_during_replan_uses_the_rules` | rules fallback |
| `test_failed_steps_run_again_and_changed_requirements_are_followed` | a failed step is kept with a note; a removed requirement disappears; a new one gets steps |
| `test_feedback_after_everything_finished_becomes_a_change_request` | change-request steps; the final review runs again (`review-v2`) after them |
| `test_edit_is_validated_then_becomes_the_next_version` | cycle / invented capability / changed finished step refused; a good edit is repaired (criteria, dependency) and becomes the next version |

### `test_agent_api.py` — agent (3.8), hooks, API (3.11) through the real app
| Test | Proves |
|---|---|
| `test_plugin_shape` | valid plug-in, both capabilities, executor slot, two hooks |
| `test_agent_returns_graph_then_report_and_is_idempotent` | `task-graph` first then `plan-report`; **redelivery makes no second model call** |
| `test_agent_without_requirements_is_an_invalid_task` | non-retryable error |
| `test_agent_replan_writes_the_next_version_of_the_same_artifact` | replan = version 2 of the same artifact |
| `test_upload_plan_edit_approve_replan_and_ownership` | PDF upload → plan with no manual step; roadmap.md; capabilities; edit 422 (cycle) / 200 (v2, approval again, old request superseded) / 409 (stale); reject needs a reason; approving v1 → 409; approve v2 → COMPLETED; `plan.approved` with the plan ref; replan after completion keeps finished steps, adds a change request and re-runs the review; another user gets 404 everywhere |
| `test_auto_approved_plan_also_announces_plan_approved` | auto-approve projects emit `plan.approved` too |
| `test_parallel_steps_overlap_in_the_event_log` | DoD: two plan steps running at the same time, from the events |
| `test_without_the_planning_plugin_the_stub_planner_and_naive_executor_run` | spec 3.9: with `planning` left out of the plug-ins, the naive executor and the stub planner still finish a project; the plan API is not mounted |

### `test_integration.py` — real infrastructure (DoD)
PDF → plan → approve over RabbitMQ + Postgres with placeholder steps taking 0.4 s: every step starts after all its
dependencies completed, at least two overlap, `plan.approved` is published, and a replan keeps the finished work.
Skips with the reason when `make infra-up` is not running.

### Manager: `tests/manager/test_replace_graph.py` (Member 1 code, made for Sprint 3)
Replace keeps the completed step's task, cancels / marks the rest `replaced`, re-gates approval (v1 approved, v2
pending), refuses a decision on v1 (`StaleGraph`), runs v2 to COMPLETED (replaced tasks do not fail the run); a failed
run reopens and completes; the version must be newer; without a plan it submits.

### Frontend: `frontend/src/features/planning/PlanPanel.test.tsx` (5 DOM tests, happy-dom; the client and the React Flow view mocked)
Shows the plan with questions, flags and the "requirements edited" banner, and approves the shown version with a
note; rejecting needs a reason; editing a step and saving sends the next version and shows the server's problems
(422); "Change plan…" sends the feedback and the failed steps; coverage shows flagged requirements.

### Frontend: `frontend/src/features/planning/logic.test.ts` (10)
Layered layout (dependencies left, crossings removed by the barycenter sweeps, survives a cycle in an unsaved edit);
add / update / remove steps immutably (dependants inherit dependencies); add / remove edges and refuse loops; local
problems before saving; version diff; coverage rows from unsaved steps; group tree ≤ 3 levels; step states in words.

## 4. Checked by hand (2026-10-13, in the browser, replay mode)
TCP chat PDF → Plan tab: version 1 "Waiting for your approval", 19 steps; the graph opens at the first steps at a
readable zoom with the critical chain outlined; selecting a step shows its criteria (including the constraints),
priority and slack. Edit → "Add a /quit command" → Save as version 2 (attached after Design with a default
criterion); Approve → steps ran with up to 3 at once and live states; Roadmap, Coverage (8/8) and Versions views;
"Change plan…" with "Don't use threads; use asyncio." → version 3 waiting for approval with all 20 finished steps
kept. At 375 px no view scrolls sideways. Light mode: graph, panel and the approve dialog (optional note) use the
light tokens.

## 5. Known gaps
- The React Flow view itself is tested by hand (it needs layout APIs happy-dom lacks); its layout is unit-tested.
- Recorded answers come from Groq `gpt-oss-120b` (Gemini answered 503 throughout recording). The demo's replan
  (after an edit, everything finished) has no recording, so replay demos take the rules path there.
- The gold set and reference plans are ours; granularity is a judgement call (see eval.md).
