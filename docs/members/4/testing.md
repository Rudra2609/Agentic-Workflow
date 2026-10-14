# Testing — refinement and observability (Member 4)

Everything runs offline. Models are scripted with `FakeLLM`, or replayed from `samples/llm_cache/refine/`. No key,
no network, no Ollama. The two integration tests need `make infra-up` (RabbitMQ + Postgres) and are skipped without it.

```bash
cd backend
uv run pytest tests/refine tests/obs tests/ops tests/manager/test_replay_dead_letter.py tests/core/runtime/test_worker_refine.py -q
uv run pytest -q                          # everything (Sprint 1–3 suites included)
cd ../frontend && npm test                # incl. features/refine and features/ops
```

## Backend (76 tests in Member 4's folders + 12 in Member 1's)

| File | Tests | What it proves |
|---|---|---|
| `tests/refine/test_stop.py` | 9 | each stop rule; `any_of` gives the first reason, `all_of` needs all; `best_index` keeps the best and, on a tie, the earlier attempt |
| `tests/refine/test_stop_property.py` | 2 | **hypothesis:** every combination of policies and score sequences stops within the cap and returns the best attempt; policies never crash |
| `tests/refine/test_refiner.py` | 10 | the loop improves to the threshold and records everything; regression guard; deterministic with FakeLLM; token accounting + budget stop; cancellation keeps the best so far; reviser failure → `error`, first-critique failure propagates; producer / critique-only modes; progress callback; hard cap; concurrent loops share no state |
| `tests/refine/test_critics.py` | 6 | critic shapes; the rubric judge scores per criterion and drops issues without a valid location; composite: programmatic first, caps, contradictions dropped, soft LLM caps and weights, judge skipped without a model or on failure (and the round records the skip) |
| `tests/refine/test_revisers.py` | 7 | JSON patches; **unflagged parts byte-identical**; targeted reviser only patches flagged locations; guards; full / schema / strategic revisers |
| `tests/refine/test_reflexion.py` | 5 | targeted → full → widen on a repeated category; the note uses the `fast` model and reaches the next prompt; memory persists per project and starts the next run at `full`; fixed problems marked fixed |
| `tests/refine/test_taxonomy.py` | 4 | the gold set covers all 10 categories and 4 severities; **rules on the held-out half: 36/40 labelled, all correct**; codes win over wording; classifier order |
| `tests/refine/test_adapters.py` | 11 | extraction: clean set has no major issue, lead-in quotes verified, invented quotes flagged, priority fix, reviser adds only verifiable non-duplicate items, judge contradicted on a verified quote, a marking rubric is not "missing requirements" and criteria are not copied; plan: critics + dependency patch through `finalize`, `add_requirement` and Reflexion switching to Member 3's replan; windows cover every document |
| `tests/refine/test_integration.py` | 7 | **off by default changes nothing**; on: requirements improve (v2) and the plan is checked, events + traces + API; project toggle; standalone `refine.run` (CSRF, 404s); decorator and mixin; RefineAgent idempotency |
| `tests/refine/test_dry_run_member5.py` | 1 | the 7-line integration in [integration.md](integration.md), executed |
| `tests/refine/test_integration_real.py` | 2 | **over RabbitMQ + Postgres** (agents in the system): refined extraction + plan; dead letter → replay as a new execution |
| `tests/obs/test_telemetry.py` | 6 | no-op when off; `safe_attrs`; **one task = one trace** Manager → bus → agent → model (in-memory exporter); **D17 scan: no prompt, document text, summary or key pattern in any exported span or in `/metrics`**; sampler gauges, dead letters, survives errors; a recently lost agent stays visible, temp queues are skipped |
| `tests/ops/test_explain_chaos.py` | 5 | "why did this task fail?" on **every `test_chaos.py` scenario**: agent crash mid-task, duplicate delivery, retries exhausted → dead letter (+ blocked steps), Manager restart (outbox replay), late report |
| `tests/ops/test_ops_api.py` | 1 | `/api/ops`: dead-letter list, explain, replay with a reason → a new attempt, ownership |
| `tests/manager/test_replay_dead_letter.py` (M1 area) | 5 | operator edges are not in the normal table; replay = new execution, retries reset, dependants unblocked, failed project back to executing; refusals; the `refine` setting reaches `TaskAssign` |
| `tests/core/runtime/test_worker_refine.py` (M1 area) | 7 | the D1 hook runs only with the flag and only on success; adapter failure → original result; cancellation; highest-priority adapter wins; the refine plug-in registers adapters for Members 2 and 3 |

Also changed in Member 1's tests: `tests/tooling/test_tooling.py` (+6 ownership rows) and
`tests/agents/stubs/test_stubs.py` (+1: the `stub_fail` / `stub_fail_times` inputs that the demo and the chaos tests
use).

## Frontend (15 tests)

| File | Tests | What |
|---|---|---|
| `features/refine/logic.test.ts` | 6 | issue grouping by worst severity, score formatting, run outcome in plain words, score curve points, diffs as sentences, event key |
| `features/refine/RefinePanel.test.tsx` | 3 | each round with problems by kind, score curve and diff; developer mode adds critics, cost, refused changes and a skipped judge; checking off → explanation and a button that turns it on |
| `features/ops/logic.test.ts` | 4 | verdict tones and one-line errors, safe task id from the URL, a real replay reason required, attempt summaries |
| `features/ops/OpsPage.test.tsx` | 2 | explains a dead letter and replays it with a reason; overview and the Jaeger / Grafana / Prometheus links |
| `tests/api.test.ts` (M1 area) | +1 | `createProject` sends `refine` only when set |

## Evaluation harnesses (not run by `pytest`; numbers in [eval](eval.md))
- `tests/refine/eval/run_eval.py`: the ablation (base vs Self-Refine vs + Reflexion) on Members 2 and 3's gold sets.
- `tests/refine/eval/taxonomy_eval.py`: labelling accuracy on `samples/refine/taxonomy_gold.jsonl`.
- `infra/observability/load/soak.py`: load / soak test.

## Checked by hand (desktop + 375 px phone, light + dark)
- Refinement tab: rounds, problems by kind, score curve, stop reason, diff.
- Operations page: explain, dead letters, the replay dialog creating new attempts.
- Jaeger: one task's trace across attempts and a replay.
- Grafana: the dashboard with data and the firing-alerts table.
- Prometheus `/alerts`: HmapDeadLetter firing.

No layout overflow at 375 px after one fix (the screen-reader-only "Actions" header needed `position: relative`).
