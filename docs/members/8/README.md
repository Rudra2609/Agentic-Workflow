# Member 8 — Automated testing & execution (Sprint 8)

| | |
|---|---|
| Plug-in | `backend/src/hmap/agents/testing/` |
| Capability | `test.run` → `test-report` / `TestReport` (`CAPABILITY_OUTPUTS`) |
| Inputs | objective + acceptance criteria; the coding step's artifacts (`workspace`, `code-change-set`) in `artifact_refs`, else `inputs.workspace_ref`, else the project head; optional `inputs.entrypoint` / `sample_input` / `long_running` (run stage), `generate_tests`, `tests` (acceptance test files supplied with the step), `mutation`, `fuzz` |
| Outputs | `tr-<task>` (TestReport), `tl-<task>` (full stage log), `tt-<task>` (testing trace), `gt-<task>` (generated tests, when any); event `test.completed`; on actionable failures a `code.revise` + a new `test.run` (the loop) |
| UI panel | `frontend/src/features/testing/` — the project's **Testing** tab |
| API | `/api/testing/...` ([design](design.md) §8; quarantine routes §9) |
| Languages | Python (image `hmap-sandbox-py:1`); JavaScript / TypeScript (image `hmap-sandbox-node:1`) |

Docs: [plan](plan.md) · [research](research.md) · [design](design.md) · [eval](eval.md) · [testing](testing.md) ·
[threat model](threat-model.md) · [gVisor / Firecracker](gvisor.md) · [core requests](core-requests.md). Samples: [`samples/testing/`](../../../samples/testing/README.md).

## Run
```bash
make sandbox-image                                    # once, with the internet: the Python + Node images (Docker running)
cd backend && uv run pytest tests/testing -q          # pipeline, analyser, test generation, loop, agent + API (local runner)
uv run pytest tests/testing -q -m integration         # + the Docker abuse tests and the seeded suite in Docker
uv run python -m tests.testing.eval.run_eval --loop --extras   # detection, loop fix rate (replay), mutation/JS/fuzz
scripts/demo_sprint_8.sh                              # TCP chat: code -> multi-client test fails -> fix -> re-test passes
```

Configuration (`.env.example`, all optional): `HMAP_TESTING_SANDBOX` (`auto` / `docker` / `local`),
`HMAP_TESTING_IMAGE`, `HMAP_TESTING_MEMORY_MB`, `HMAP_TESTING_STAGE_TIMEOUT_S`, `HMAP_TESTING_CONCURRENCY`,
`HMAP_TESTING_AUTO_REVISE`, `HMAP_TESTING_MAX_ROUNDS`, `HMAP_TESTING_GENERATE`, `HMAP_TESTING_MUTATION`,
`HMAP_TESTING_MUTANTS`, `HMAP_TESTING_FUZZ`, `HMAP_TESTING_DEP_AUDIT`, `HMAP_TESTING_RUNTIME`, `HMAP_TESTING_IMAGE_NODE`.

## Limitations
- Python and JS/TS only. JS uses Node's built-in test runner: Jest / Mocha suites do not run (nothing is installed
  at test time). JS projects need Docker; the local runner is Python only. Test generation, mutation and fuzzing are
  Python only.
- Containers share the host kernel: the sandbox stops accidents and casual abuse (proven by 8 attack cases), not a
  kernel exploit. gVisor is installed in Colima and one setting away (`HMAP_TESTING_RUNTIME=runsc`, ~30 % slower,
  [gvisor.md](gvisor.md)); Firecracker needs KVM. Without Docker the local jailed runner is weaker (no memory / process limits) and the report says so.
- The dependency audit only knows pinned versions and needs the network (live mode) or an earlier cached answer.
- The rule classifier was written next to the seeded suite; on Member 7's unseen bug-fix tasks it detected 9/9 with
  no false alarm, but categories of unusual failures can still be off (the `classify` model is the fallback).
- Generated tests are only as good as the criteria; the sanity gate removes tests that check nothing, not tests that
  check the wrong thing. Their failures are shown but never start a revision on their own.
- The loop helps when a failure says what to change; a fix that needs a change the project's own tests forbid (e.g.
  a different protocol than the template's tests) is rolled back by the coding agent's regression guard and the loop
  stops after its rounds.
