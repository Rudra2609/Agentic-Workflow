# Sprint 8 — Member 8: Automated Testing & Execution

**Owner:** Member 8 · **Needs:** Sprint 7 accepted · **Unblocks:** Sprint 10 (review uses `TestReport`)
**Replaces stub:** `test.run` → `agents/testing/`

## 1. Goal
Safely execute generated code in **Docker sandboxes**, run static analysis → build → unit → integration → security checks, analyze failures, and produce a `TestReport` with **actionable feedback** that drives an automated **code→test→refine loop with Member 7**.

## 2. Provided
`CodeChangeSet` (workspace artifact), acceptance criteria, `code.revise` capability, M4 Refiner/StopPolicy, gateway (`coder` for test generation, `reasoner` for failure analysis), UI shell. **Docker must be installed** (doc 00).

## 3. Research deliverable
Testing pyramid (unit/integration/e2e), property-based testing, LLM-generated tests (pitfalls: tests that assert bugs), static analysis (ruff, mypy, pylint), security (bandit, semgrep, secrets scanning, dependency audit), **container sandboxing** (namespaces/cgroups, seccomp, rootless, no-network, read-only FS, resource limits, escape risks), flaky test handling, failure triage/classification, test-driven repair loops.

## 4. Design

```text
CodeChangeSet + acceptance_criteria
 → [Test planner] discover existing tests; if missing/insufficient → LLM generates tests from acceptance criteria (marked "generated", reviewed by static checks)
 → [Sandbox runner] docker run --rm --network=none --read-only --pids-limit --memory --cpus --user nonroot --tmpfs /tmp  (workspace mounted read-only copy → writable overlay), hard timeout, output caps
 → stages: static(ruff,mypy) → build/import → unit(pytest) → integration(multi-process / compose-less docker network, e.g. TCP server+N clients) → security(bandit, secret scan, dep audit) → execution (run entrypoint w/ sample inputs)
 → [Failure analyzer] parse outputs → classify {SYNTAX, IMPORT, ASSERTION, TIMEOUT, CRASH, SECURITY, LINT, ENV} → map to file/line → hint (LLM+rules)
 → TestReport  → if failed & budget: send revision.request(required_changes from analysis) to Manager→M7  (loop bounded by M4 StopPolicy)
```
**Docker-socket trade-off (document in design.md):** an agent container with `/var/run/docker.sock` can escape to the host. Choices: (a) run the testing agent **on the host** (not in compose) — recommended for this project; (b) use a docker-socket-proxy limiting API calls; (c) rootless Docker/sysbox. Decide & justify.

## 5. Work items

### MUST
| # | Item | Files (`agents/testing/`) | Acceptance |
|---|---|---|---|
| 8.1 | Sandbox runner (Docker SDK): images (`hmap-sandbox-py` prebuilt with pytest/ruff/mypy/bandit), limits, no-network default, timeouts, cleanup/reaping | `sandbox/` | escape/abuse tests: fork bomb, infinite loop, big output, network attempt, write outside |
| 8.2 | Stage pipeline + per-stage results/streamed logs | `pipeline.py` | stage statuses + artifacts |
| 8.3 | Static analysis stage (ruff, mypy; configurable strictness) | `stages/static.py` | |
| 8.4 | Unit test stage (pytest JSON report), coverage % | `stages/unit.py` | |
| 8.5 | Integration stage (multi-container/process orchestration, e.g., TCP server + clients; ports isolated per run) | `stages/integration.py` | TCP-chat multi-client scenario passes/fails correctly |
| 8.6 | Security stage (bandit, secrets regex, optional pip-audit offline DB) | `stages/security.py` | seeded vulnerable code flagged |
| 8.7 | Test generation from acceptance criteria (+ sanity gate: generated tests must fail on a known-bad stub & pass on known-good where available) | `testgen.py` | |
| 8.8 | Failure analyzer & classifier (rules first, then `ctx.llm.classify` for the category) → `failures[]` with file/line/hint | `analyze.py` | accuracy on seeded failures |
| 8.9 | **Refinement loop with M7**: report → `revision.request` → rerun; bounded; uses M4 StopPolicy; plateau detection | `refine_loop.py` | fixes ≥ X % of seeded failures |
| 8.10 | `TestingAgent` capability `test.run`; streaming progress; cancellation kills containers | `agent.py` | on bus; idempotent |
| 8.11 | Resource governance for 16 GB (concurrency=1, image pre-pull, cache) | `governor.py` | stack + sandbox coexist |
| 8.12 | **Seeded-failure suite**: good code + 15 broken variants (syntax, import, logic, concurrency bug, insecure code, timeout) | `samples/testing/` | |
| 8.13 | Eval: detection rate, false-pass rate, classification accuracy, sandbox overhead, loop success rate | `tests/testing/eval/` | `eval.md` |
| 8.14 | API + UI: pipeline stage timeline, log viewer, failure list w/ hints, “re-run”, loop iterations | `agents/testing/router.py` (auto-mounted), `frontend/src/features/testing/` (auto-registered) | |
| 8.15 | Tests (sandbox needs Docker; mark integration; replay for LLM parts) | `tests/testing/` | green |

### STRETCH
JS/TS projects; mutation testing; fuzzing; per-language images; gVisor/Firecracker evaluation write-up; flaky-test quarantine.

## 6. Local-LLM notes
`coder` for test generation; `reasoner` for failure analysis; most of the pipeline is **LLM-free** (deterministic) — keep it that way. Sandbox + Ollama + Docker stack must fit 16 GB.

## 7. Interface handed to Member 9 / 10
```text
Artifact: TestReport {stages{…}, failures[{category,file,line,message,hint}], passed, coverage, exec_log_ref}
Event: test.completed {task_id, report_ref, passed}
Loop: test.failed → Manager → code.revise (≤N rounds) → test.run
Review (M10) consumes TestReport as objective evidence; Docs (M9) can call the sandbox to *verify code examples* it writes.
```

## 8. Definition of Done (additions)
- [ ] Sandbox abuse tests all contained; documented threat model
- [ ] Detects ≥90 % of seeded failures, 0 false-pass on known-good
- [ ] Full loop demo: code agent output fails multi-client test → revise → pass (the guide’s §32 scenario)
- [ ] Demo `demo_sprint_8.sh`

## 9. Risks
Docker-socket escape → host-run agent/proxy; resource exhaustion → limits + governor; LLM-generated tests are wrong → sanity gate, label as generated, objective failure ≠ trust blindly; port collisions → per-run networks.
