# Member 9 — Technical documentation + the one-command laptop demo (Sprint 9)

| | |
|---|---|
| Plug-in | `backend/src/hmap/agents/docgen/` |
| Capabilities | `docs.generate` → `doc-bundle` / `DocBundle` (`CAPABILITY_OUTPUTS`); `docs.update` (same output, after a code change) |
| Inputs | software: `inputs.files`, else the newest `workspace` in `artifact_refs`, else `inputs.workspace_ref`, else the project head `wsh-<project>`; a `test-report` feeds the report. Document projects: the `research-report` + `verification-report` + `requirement-set`, `inputs.phase` (`design` = outline). `docs.update`: `inputs.previous_bundle` or `dh-<project>` |
| Outputs | `db-` DocBundle, `drd-` README, `dap-` API, `dar-` architecture, `dsu-` summaries, `drp-` report, `dac-` accuracy (every claim), `dfa-` facts, `dtr-` trace; head `dh-<project>`; event `docs.completed`; hook `code.completed` → `docs.update` |
| UI panel | `frontend/src/features/docgen/` — the project's **Docs** tab (preview, highlighted ungrounded sentences, examples, Regenerate, "Check a sentence") |
| API | `/api/docgen/...` ([design](design.md) §8) |
| Platform work | `make demo` (live) / `make demo-replay` / `make stop` / `make reset-demo` / `make report`, `scripts/demo_preflight.py`, the [configuration reference](platform/configuration.md), the [platform docs](platform/README.md) |

Docs: [plan](plan.md) · [research](research.md) · [design](design.md) · [eval](eval.md) ·
[core requests](core-requests.md) · [platform docs](platform/README.md). Samples: [`samples/docgen/`](../../../samples/docgen/README.md).

## Run
```bash
cd backend && uv run pytest tests/docgen -q                       # extractor, grounding, generators, agent + API, demo tools
uv run python -m tests.docgen.eval.run_eval                       # rules: seeded false claims + false alarms (seconds)
uv run python -m tests.docgen.eval.run_eval --generate --free     # + the agent on 10 repositories (recorded answers)
uv run python -m hmap.agents.docgen.config_reference              # regenerate docs/members/9/platform/configuration.md
scripts/demo_sprint_9.sh                                          # code -> docs -> grounding; false claims flagged; docs.update
make demo-replay                                                  # the whole platform, offline; make stop
```

Configuration (`.env.example`, all optional): `HMAP_DOCGEN_SUMMARY_LIMIT`, `HMAP_DOCGEN_MAX_ROUNDS`,
`HMAP_DOCGEN_RUN_EXAMPLES`, `HMAP_DOCGEN_AUTO_UPDATE`, `HMAP_DEMO_MIN_FREE_GB`.

## Limitations
- Python repositories are documented in full; for JavaScript only `package.json` (dependencies, scripts) is read.
- The rules check concrete claims (technology, endpoint, env var, path, symbol, flag, command, port, version,
  citation). Behaviour claims need the model; a behaviour claim the code does not clearly show stays "not verified"
  (listed, not counted as wrong).
- Routes mounted in ways the AST cannot follow (plug-in routers mounted by the platform) need the app's OpenAPI
  document: generated apps get it in the sandbox only when the sandbox has the app's dependencies (the Docker image
  has no FastAPI); otherwise the AST routes are used.
- Documented examples run only when they are safe and finish (Python snippets, `--help`, tests); servers, installs
  and network commands are checked against the facts, not run.
- The coverage number counts public functions and classes with a docstring or a model summary, up to
  `HMAP_DOCGEN_SUMMARY_LIMIT` model summaries per run.
- `make stop` force-stops any `uvicorn hmap.api.app`, `hmap-agents` and `next` process on this machine, also one you
  started by hand with `make api`.
- The human rubric in [eval.md](eval.md) §4 was filled in by the assistant that built the sprint; Member 9 should
  re-score it.
