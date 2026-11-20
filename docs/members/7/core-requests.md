# Requests to Member 1 (core / shared files)

Anything you need changed outside your own paths (`ownership.toml`): describe it here, Member 1 implements it.

| # | Date | File / area | What and why | Status |
|---|---|---|---|---|
| 1 | 2026-10-24 | `ownership.toml` | `[cross_cutting] 7` rows for the shared files of [plan](plan.md) §5 (Q6) | approved + added by Member 1, 2026-10-24 |
| 2 | 2026-10-24 | `backend/src/hmap/core/config.py`, `.env.example` | `HMAP_CODING_*` settings (work dir, interpreter, sandbox, prompt budget, step / debug / revision limits, command timeout) | approved 2026-10-24 (plan step 3) |
| 3 | 2026-10-24 | `Makefile` | `coding-venv` target: `data/coding/venv` with pinned `pytest`, `fastapi`, `httpx`, no `hmap` (Q2) | approved 2026-10-24 |
| 4 | 2026-10-24 | runner isolation | best-effort macOS `sandbox-exec` (no network, no reads of the project folder / home) until Member 8's Docker runner; off on Linux / CI (Q3) | approved 2026-10-24 |
| 5 | 2026-10-24 | revision flow | `code.revise` is a normal task (`inputs.revision_of`, `required_changes`) created through `ManagerHandle.create_task`; no `revision.request` handler, no automatic test→revise loop in Sprint 7 (Q4) | approved 2026-10-24; no core change |
| 6 | 2026-10-24 | `backend/tests/verify/security/test_injection.py` (Member 6) | switch on the repository entry point for `code.implement` with `samples/verify/injection/repo/` (finding F3) (Q5) | approved 2026-10-24 |
| 7 | 2026-10-24 | per-project workspace head | `wsh-<project_id>` artifact; `CodeChangeSet.workspace_ref` = full tree after the task, `patch_ref` = this task's diff (Q1) | approved 2026-10-24; no contract change |
| 8 | 2026-10-24 | `scripts/demo_sprint_7.{sh,py}`, `README.md`, `HANDOFF.md` | Sprint 7 demo, "real vs stub" table, Sprint 7 handoff section | approved 2026-10-24 |
| 9 | 2026-10-25 | `backend/pyproject.toml` | `[tool.mypy] exclude = ["src/hmap/agents/coding/templates/"]`: the templates are sample projects for generated code (shown to the model byte for byte; typing them would change every recorded prompt) | approved by Member 1, 2026-10-25 |
