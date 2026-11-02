# Testing — Member 7: Autonomous coding (Sprint 7, item 7.15)

```bash
cd backend
uv run pytest tests/coding -q                                  # unit + loop + agent/API (fake model), ~1.5 min
uv run pytest tests/coding/test_integration_real.py -q         # RabbitMQ + Postgres (make infra-up), else skipped
uv run pytest tests/verify/security/test_injection.py -q       # Member 6's suite, code.implement switched on
uv run python -m tests.coding.eval.run_eval                    # the benchmark in replay (recorded answers)
python3 ../samples/coding/check_benchmark.py                   # every task is fair (no project code needed)
cd ../frontend && npx vitest run src/features/coding           # Coding tab
```

No test needs a model, a key or the network (scripted `FakeLLM`; the eval replays `samples/llm_cache/coding/`).
The sandbox tests run on macOS only (`sandbox-exec`); on Linux they skip with the reason.

| File | What it proves |
|---|---|
| `test_workspace.py` | 7.1: jail (`..`, nested `..`, absolute, `~`, symlink file and folder, NUL, empty); `.env` / caches never part of a workspace; work folder never inside the project; deterministic tarballs; tar-slip, links, devices, size caps refused; diff (create/change/delete); three-way merge and rebase on a moved head |
| `test_runner.py` | 7.4: 16 denied commands (shell, rm, curl, `-c`, other modules, pip, scripts or paths outside, `ruff format`); allowed ones run; no keys / `HMAP_*` reach generated code and `import hmap` fails; **sandbox: `.env`, project files and home unreadable, writes outside refused, internet blocked, localhost TCP works**; endless loop killed, output flood capped, cancel kills the command; output normalisation (paths, timings, addresses, ports, temp names) |
| `test_edits_and_tools.py` | 7.5: exact / create / every refusal message / tolerant whitespace and indentation / atomic syntax refusal / no-op refusal / fenced answers; file tools (wrapping cannot be forged, injection flags, search); checks report compile, lint, import and test failures |
| `test_repomap_budget_templates.py` | 7.2: symbols and signatures, every benchmark map ≤ 1,500 tokens, incremental rebuild parses only the changed file; 7.8: required parts kept, property test (150 cases) never over budget, windows; 7.10: four templates, keyword choice, **every template passes its own checks in the runner** |
| `test_loop.py` | 7.6 / 7.7 with a scripted model: happy path (hidden tests pass), refused edit fed back then fixed, failing tests drive a debug round (hypothesis recorded), budget → `partial` with Reflexion notes, step budget, no model answer → template + `partial`, greenfield template, cancel, **every prompt within budget, no paths or durations, temperature 0 / seed 7**, regression guard, nothing changed ≠ success, "NO CHANGES" = success |
| `test_agent_api.py` | 7.9 / 7.14 on the in-memory bus: `code.implement` → 4 artifacts in order, hidden tests pass, `code.completed`; every API route incl. path traversal → 400, other user → 404, zip; head versions; **"Request changes" → `code.revise` from the head (both changes in the tree, only the new one in the patch), limit → 409**; greenfield without a model completes; idempotent redelivery; `stub_fail`; two parts merged into one head; **`code.revise` fixes a seeded failing change from a `TestReport`** (DoD) |
| `test_injection_repo.py` | Member 6's poisoned repository through the whole loop: untrusted note in every prompt, poison only inside FILE blocks, every file flagged, an obeying model's `.env` / `../` edits refused, `curl` denied |
| `test_integration_real.py` | RabbitMQ + Postgres: implement → artifacts → event → revise → head v2 (`@pytest.mark.integration`) |
| `frontend/src/features/coding/*.test.ts(x)` | diff parsing, tool-call log order, words, event key; panel shows log/diff/flags/download, "Request changes" sends one change per line |

Regression: the whole backend suite stays green with the real agent replacing the stub (the e2e and Manager tests
use the fake model; the agent degrades instead of failing).
