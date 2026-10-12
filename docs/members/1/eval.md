# Evaluation — Member 1: communication layer, Manager core, platform skeleton

Measured on 2026-10-11 on the demo laptop (Apple Silicon, 16 GB, macOS), Python 3.11, Colima (2 CPU / 2 GB) running
`pgvector/pgvector:pg16` (host port 5433) and `rabbitmq:3.13-management`.

## 1. What is evaluated
Sprint 1 has no model output to grade; its "gold set" is the set of **failure scenarios** a reliable communication
layer must survive (research §36), plus the end-to-end demo. Inputs: `samples/demo/tcp_chat_assignment.txt`.

## 2. Metrics
| Metric | Definition | Target |
|---|---|---|
| Correctness | backend + frontend test suites green | 100 % |
| Message safety | messages lost / effects duplicated across crash, redelivery and broker restart | 0 / 0 |
| State safety | terminal or newer state ever overwritten by a late/duplicate/stale report | never |
| End-to-end | upload → plan → approval → all tasks COMPLETED, on the real stack, agents in a separate process | pass |
| Gateway | same answer in `live` (Ollama) and `replay`; replay makes no model call | identical |
| Team safety net | regression check attributes a breakage to the right change/owner; pre-existing failures not blamed | correct |

## 3. Results

### 3.1 Test suites (`scripts/check_sprint.sh 1`: PASS)
| Area | Tests | Notes |
|---|---|---|
| `tests/core` (contracts, bus incl. RabbitMQ adapter, LLM gateway + key pool, runtime, config + `.env`) | 348 | |
| `tests/manager` (transitions, CAS, assignment, retries, watchdog, DAG, approval, auto-approve, Stop) | 115 | |
| `tests/services` (registry, context, artifacts) | 39 | |
| `tests/db` (Postgres stores, migrations, outbox ordering) | 54 | integration |
| `tests/e2e` (chaos + stub pipeline + full stack) | 10 | 3 full-stack on RabbitMQ + Postgres |
| `tests/contracts` (snapshot compatibility, plug-in conformance) | 22 | |
| `tests/api` (incl. accounts 18, two-user isolation 6), `tests/agents` | 50 | |
| `tests/tooling` (regression attribution, ownership, manifests, secret scan) | 31 | |
| **Backend total** | **687** | 103 of them `integration` (need `make infra-up`); ruff + mypy --strict (99 files) clean |
| Frontend (vitest) | 72 in 9 files | + eslint (0 warnings), `tsc`, `next build` |

### 3.2 Failure scenarios
| Scenario | Test | Result |
|---|---|---|
| Agent crash mid-task | `e2e/test_chaos.py::test_agent_crash_mid_task_recovers_on_another_agent` | redelivered, new execution, project completes |
| Duplicate message | `e2e/test_chaos.py::test_duplicate_assignment_is_processed_once` | inbox dedup hit, one effect |
| Retries exhausted → DLQ | `e2e/test_chaos.py::test_retries_exhausted_dead_letters_and_blocks_dependants` | DEAD_LETTERED, dependants BLOCKED |
| Manager restart (outbox replay) | `e2e/test_chaos.py::test_manager_restart_replays_outbox` (memory) and `e2e/test_full_stack.py::test_manager_restart_recovers_from_postgres` | a new Manager on the same database finishes the project |
| Late / out-of-order replies | `e2e/test_chaos.py::test_late_started_after_completed_does_not_regress`, `manager/test_manager.py::test_out_of_order_started_before_ack` | no state regression |
| Result after timeout | `manager/test_manager.py::test_result_after_ack_timeout_is_kept_as_evidence_only` | stored as evidence, no state change |
| Broker restart | `core/bus/test_rabbitmq_adapter.py::test_broker_restart_loses_no_message` (`docker restart`) | **20/20** confirmed commands delivered, each effect once |
| Consumer reconnect | `…::test_unacked_messages_survive_a_consumer_reconnect` | unacked messages redelivered |
| Unparseable message | `…::test_unparseable_message_goes_to_dlq` | to `hmap.dlq` with the reason |

### 3.3 End to end
| Run | Stack | Result |
|---|---|---|
| `scripts/demo_sprint_1.sh` | in-memory bus + stores, `fake` LLM | DEMO PASS: 9 agents, 7 tasks COMPLETED |
| `DEMO_SPLIT=1 HMAP_BUS=rabbitmq HMAP_STORE=postgres scripts/demo_sprint_1.sh` | RabbitMQ + Postgres, agents in their own process (`hmap-agents run --all`) | DEMO PASS: 7 tasks, 71 events |
| Dashboard (manual, browser) | API + `next start` | project created in the UI, plan appeared live at the approval gate, approved in the UI, 7 tasks went COMPLETED live; Agents (9, heartbeat age), Events and Dead-letters pages render; no console errors |

The two-process run found a real bug that single-process tests could not: relative `HMAP_ARTIFACT_ROOT` /
`HMAP_LLM_CACHE_DIR` resolved against each process's working directory, so `make api` (run from `backend/`) looked
for replay caches in `backend/samples/`. Fixed (paths are anchored to the repo root) with a regression test
(`tests/core/test_core_utils.py::test_relative_paths_resolve_against_repo_root`).

### 3.4 LLM gateway (`scripts/llm_check.sh`)
| Mode | Calls | Time | Result |
|---|---|---|---|
| `record` (live Ollama, `qwen3.5:9b` + `nomic-embed-text`) | free text, schema JSON, `classify`, `embed` (768-d) | 26.5 s (11 s of it model load) | schema JSON valid first try |
| `replay` (Ollama URL pointed at a dead port) | same 4 | < 0.01 s | identical answers → **LLM CHECK PASS** |

Model choice and its quality numbers: `docs/members/11/model-choice.md`.

### 3.5 Team safety net (regression attribution)
Scenario built from two copies of the repo: the base already contains a failing Member 3 test; the current tree adds
Member 2's (passing) tests **and** someone else's one-line edit to `core/errors.py` (TIMEOUT no longer retryable).

`scripts/regression_check.sh --base <base> --current <current> --member 2 -- -m "not integration"` → exit 1 and:
- `NEW_FAILURE = 3` (all three tests that depend on TIMEOUT being retryable), confirmed by re-runs (failed, failed);
- `PRE_EXISTING = 1`: Member 3's test, reported as **not caused by this change**;
- *Likely cause:* `backend/src/hmap/core/errors.py (M1)`; "**Not caused by Member 2:** … look at the changes by M1";
- ownership: the core edit is flagged "needs Member 1 sign-off".

Run time: base 18 s + current 17 s + re-runs.

### 3.6 Accounts and data isolation
| Check | Test | Result |
|---|---|---|
| Register / sign in / sign out / generic errors / expired session / CSRF / rate limit / reset (single use, expiry, no enumeration) | `tests/api/test_auth.py` | 18 pass |
| User B cannot list, read, change, stop, approve, delete, upload to, re-run, or download from User A's project, nor see A's events, WebSocket stream or dead letters | `tests/api/test_isolation.py` | 6 pass (every attempt is 404, the same as a missing project) |
| Passwords, session and reset tokens never stored in clear (Postgres) | `tests/db/test_pg_accounts.py` | pass |
| Session, project, run history, files and activity survive a server restart | `tests/e2e/test_full_stack.py::test_workspace_survives_a_server_restart` | pass |
| Browser: register → create project from text → plan review → inspector → approve → live completion; API restart keeps the session and project; light/dark/mobile layouts | manual, built-in browser | as described |

## 4. Comparisons
- In-memory adapters vs RabbitMQ/Postgres: same contract tests run against both (`tests/core/bus`, `tests/db`),
  so tests that use the fast in-memory stack check the same semantics as the demo stack.
- Transport and orchestration alternatives: `research.md` §3.

## 5. Honest limitations
- One Manager per database (replies are consumed with prefetch 1 plus a process-local lock).
- No `agent.registered` reply: a rejected agent is not told (design.md §7).
- The per-project cloud switch (`cloud_ok`) applies to steps assigned after it changes; a step already running keeps
  its client. It only binds agents that use `ctx.llm` (every agent should; none builds its own client).
- Capability queues have no broker-level dead-letter exchange; exhausted work is dead-lettered by the Manager/retry
  path, and unparseable messages by the adapter.
- The broker-restart test restarts the shared dev broker (it is marked `slow` and skips without Docker).
- Regression check: a flaky test that happens to pass on both first runs is not re-run, so it shows as PASSING.
- Load/soak numbers (throughput, latency percentiles) are Member 4's Sprint 4 work.
