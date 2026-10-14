# Member 5 — Autonomous research

A plan's research step (or a question asked in the dashboard) becomes a **cited research report**:

1. The questions are split into sub-questions.
2. Search covers Wikipedia, arXiv, DuckDuckGo and an offline corpus of saved pages.
3. Pages are fetched politely and safely, cleaned, and indexed (keywords + embeddings).
4. The best passages are picked with an explainable score.
5. Quotes are extracted and **checked word for word** against the saved page.
6. Coverage is tracked per sub-question, and the step stops on a clear rule.
7. Claims are written, each citing its evidence.

It works with Wi-Fi off: the default `cached` mode never touches the network.

| | |
|---|---|
| Plug-in | `backend/src/hmap/agents/research/` (priority 100; replaces the `research.run` stub) |
| Capability | `research.run` → `research-report` (`ResearchReport`) + `research-trace`, `research-brief`, `research-page` (one per cited page) |
| Inputs | `inputs.research_questions` (Member 3's plan), else the objective; scope from the latest `requirement-set`; `inputs.budget`; `inputs.follow_up_of` (Member 6: research only the gaps); `inputs.research_mode` |
| Modes | `HMAP_RESEARCH_MODE` = `cached` (default, never the network) · `online` · `local`; `HMAP_RESEARCH_PROVIDERS` |
| Events | `task.progress` per round (trace ref); `research.completed {task_id, report_ref, stop_reason, claims, evidence, sources, coverage}` |
| Index | migration `005_sprint_5_research` (`research_chunks`, pgvector + tsvector); memory backend without Postgres |
| UI | project tab **Research** (`frontend/src/features/research/`): sub-questions with coverage, cited findings, evidence viewer (quote highlighted in the saved page), sources with score breakdown, rounds |
| API | `GET /api/research/runs/{project_id}[/{task_id}]`, `GET /api/research/pages/{project_id}/{artifact_id}?task_id=`, `POST /api/research/runs/{project_id}`, `GET /api/research/providers` |
| For later members | Member 6: `get_providers()`, `Fetcher`, `quotes.locate`, page artifacts + sha256, `follow_up_of`, `samples/research/adversarial/`; Member 7: `index.HybridIndex`; Member 11: `samples/research/gold` + `tests/research/eval` |
| Docs | [plan](plan.md) · [research](research.md) · [design](design.md) · [eval](eval.md) · [testing](testing.md) |

## Run
```bash
cd backend && uv run pytest tests/research -q                 # unit, property, API (+ Postgres / RabbitMQ with infra up)
uv run python -m tests.research.eval.run_eval --ablation        # 10 gold questions, offline (cached + replay)
uv run python -m tests.research.eval.run_eval --mode live --local-only   # local qwen3.5:9b, never recorded
uv run python -m tests.research.eval.run_eval --harvest         # ONLINE: refresh search results + pages
uv run python -m tests.research.eval.run_eval --curate          # keep only permissively licensed pages
HMAP_LLM_RECORD_MISSING=research uv run python -m tests.research.eval.run_eval --ablation   # record what is missing
cd .. && scripts/demo_sprint_5.sh                               # demo (offline; --live for real models)
```

## Limitations
- Coverage of the gold facts is 0.65 with the cloud model (see [eval](eval.md)): every quote is verified, but
  facts the corpus does not contain cannot be found. The offline corpus is only what the online search
  found **and** may be redistributed (Wikipedia, Python docs, arXiv abstracts, a few framework docs). Most blog and
  tutorial results are left out, so some questions have no good page offline.
- Research questions that only the team can answer ("Which Python version does our project use?") cannot be
  researched on the web. The report says "No sourced answer found" rather than guessing.
- DuckDuckGo often rate-limits. Wikipedia and arXiv carry most of the online searching.
- **A local-only run (qwen3.5:9b) found nothing**: the model returned no quotes, so every question ended
  `no_sources` (1.5–4 min each; [eval](eval.md) §4). With the team's cloud keys every chat role goes to the cloud
  first (fact coverage 0.65). Recommended fix for later: a rule-quote fallback when the model returns none.
- Support of a claim by its quote is checked only lightly here (the citation check: shared words). Real
  entailment checking is Member 6's verification.
