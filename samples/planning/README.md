# Planning samples (Member 3)

- `gold/content.py`: which of Member 2's gold cases are planner inputs, plus two hand-written requirement sets
  (`adversarial`: things only a person can do, a low-confidence requirement, an open question; `essay`: a writing
  project). Written for this project (no third-party text).
- `gold/build_inputs.py`: makes `gold/inputs/<case>.requirement_set.json` and `<case>.sections.json` (the document
  model trimmed to block id → section path) by running Member 2's pipeline in replay mode. Deterministic; re-run
  after Member 2 re-records: `cd backend && uv run python ../samples/planning/gold/build_inputs.py`
- `gold/references.py`: hand-made reference plans, must-have dependencies and expected flags per case (format in
  the file's docstring).

| Case | From | What it tests |
|---|---|---|
| tcp_chat | g01 (guide §32) | the golden scenario: server, nicknames, broadcast, private messages, history, quality |
| lab_manual | g02 | writing tests is the build work; coverage measured after the tests exist |
| rubric | g03 | almost only marking criteria; "every member presents the demo" must be flagged |
| project_brief | g06 | booking before capacity / CSV; deliverables table |
| multipart | g08 | Part A / B / C as parts; B uses A's schema, C tests B |
| request | g09 | a typed two-line request must not be over-planned |
| long_lab | g10 | 16 requirements from lead-in lists; model before code, logic before CLI and tests |
| adversarial | hand-written | demo in person + upload to Moodle flagged; a 0.6-confidence requirement asked about |
| essay | hand-written | the document template (writer / fact-checker steps) |

- `eval_results/`: output of `backend/tests/planning/eval/run_eval.py` (`rules`, `record` = cloud, `replay`,
  `live-local` = local `qwen3.5:9b`). Per case: scores, the plan's steps, repairs and questions.
- Recorded model answers for tests and demos: `samples/llm_cache/planning/` (replay mode).
