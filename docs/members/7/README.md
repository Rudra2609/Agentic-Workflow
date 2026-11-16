# Member 7 — Autonomous coding (Sprint 7)

| | |
|---|---|
| Plug-in | `backend/src/hmap/agents/coding/` |
| Capabilities | `code.implement` → `code-change-set` / `CodeChangeSet` (`CAPABILITY_OUTPUTS`); `code.revise` → the same |
| Inputs | objective + acceptance criteria; the project's requirement set (context); optional `inputs.workspace_ref`; for `code.revise`: `inputs.revision_of`, `required_changes`, `revision_round`, test / review reports in `artifact_refs` |
| Outputs | `ccs-<task>` (CodeChangeSet), `ws-<task>` (workspace tarball), `patch-<task>` (this step's diff), `ct-<task>` (trace); the project head `wsh-<project>`; event `code.completed` |
| UI panel | `frontend/src/features/coding/` — the project's **Coding** tab |
| API | `/api/coding/...` ([design](design.md) §7) |

Docs: [plan](plan.md) · [research](research.md) · [design](design.md) · [eval](eval.md) · [testing](testing.md) ·
[core requests](core-requests.md). Benchmark: [`samples/coding/`](../../../samples/coding/README.md).

## Run
```bash
make coding-venv                                      # once: the interpreter for generated code (pytest, fastapi)
cd backend && uv run pytest tests/coding -q           # unit + loop + agent/API tests (fake model)
uv run python -m tests.coding.eval.run_eval           # benchmark in replay: pass@1, edit-apply, locator, ablations
HMAP_LLM_MODE=replay make agents                      # the agent with recorded answers
scripts/demo_sprint_7.sh                              # TCP chat: plan -> code (design + parts) -> request changes
```

Configuration (`.env.example`, all optional): `HMAP_CODING_WORK_DIR`, `HMAP_CODING_KEEP_WORK`, `HMAP_CODING_PYTHON`,
`HMAP_CODING_SANDBOX`, `HMAP_CODING_PROMPT_TOKENS`, `HMAP_CODING_MAX_STEPS`, `HMAP_CODING_MAX_DEBUG_ROUNDS`,
`HMAP_CODING_MAX_REVISIONS`, `HMAP_CODING_CMD_TIMEOUT_S`.

## Limitations
- Python projects only; tasks must be small (the planner's depth cap keeps them so). The local `qwen3.5:9b` is much
  slower and weaker than the cloud coder ([eval](eval.md)).
- The runner is a lightweight boundary: macOS `sandbox-exec` (no file reads under the project or home, no internet)
  is best effort and absent on Linux; no memory / process limits. Member 8's Docker sandbox is the hard boundary.
- The agent runs the workspace's existing tests only; it does not write test suites (Member 8). Its own "success"
  means "my checks pass", not "the requirement is met" — hidden tests / Member 8 / Member 10 decide that.
- No automatic test → revise loop yet (the `test.run` stub always fails); `code.revise` is started by the
  "Request changes" button now and by Members 8 / 10 later.
- Recordings cover the benchmark and the TCP-chat demo storyline; other projects need `--record-missing` once.
