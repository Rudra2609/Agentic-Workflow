# Sprint 1 — Member 1: Communication Layer, Manager Core & Platform Skeleton

**Owner:** Member 1 · **Starts:** after doc-00 prerequisites · **Unblocks:** everyone
**Source research:** `Multi_Agent_Communication_Research.md` (all section numbers below refer to it)

## 0. Build status (updated 2026-10-11): **Sprint 1 DONE**

`scripts/check_sprint.sh 1` → PASS:
- backend: 687 tests, 103 of them integration tests on RabbitMQ + Postgres; ruff and mypy clean;
- frontend: lint, typecheck, 83 tests and build;
- demo in memory, and on RabbitMQ + Postgres with agents in their own process.

Details: `HANDOFF.md`, `docs/members/1/eval.md`.

| Item | Status |
|---|---|
| 1.1 bootstrap, 1.2 infra compose (Postgres :5433, RabbitMQ), 1.3 contracts (31 JSON Schemas), 1.4 ids/tracing/errors, 1.5 DB migrations (Alembic `001`, run on start) | ✅ |
| 1.6 state machine, 1.7 bus (in-memory + RabbitMQ), 1.8 outbox/inbox (memory + Postgres), 1.9 registry, 1.10 context, 1.11 artifacts (local FS + Postgres metadata) | ✅ |
| 1.12 agent runtime, 1.13 Manager core, 1.15 API + WebSocket, 1.16 stubs, 1.18 plug-in discovery + agent host | ✅ |
| 1.14 LLM gateway (all 4 modes, live check against Ollama: `scripts/llm_check.sh`), 1.14b cloud key pool | ✅ |
| 1.17 frontend shell (projects, live tasks/events, approval, agents, dead letters, feature panels) | ✅ |
| 1.19 tests, all 7 failure scenarios incl. broker restart (20/20, no loss) | ✅ |
| 1.20 handoff kit (`check_sprint`, `make_handoff`, `seed`, `demo_sprint_1`, `CONTRIBUTING.md`, `HANDOFF.md`, `samples/`, templates), §3.1 member docs | ✅ |
| §5 DoD: CONTRIBUTING dry run (<30 min, own folders only) | ✅ |

Beyond the plan:
- `pipeline` plug-in (upload → extract → plan → approval);
- `hmap/system.py` composition root;
- team test kit: `make precommit`, regression attribution with a "likely cause" section, ownership check, contract
  snapshot, plug-in conformance tests, secret scan;
- `GET /api/llm/usage` (key pool by fingerprint);
- per-project auto mode (plan shown, no approval step) and a red Stop button (`POST /api/projects/{id}/stop`);
- per-project "keep on this computer" switch (`cloud_ok`, doc 02 §2.5), enforced by the agent runtime;
- several documents or whole folders in one upload (one run; names and folders reach `document.extract`);
- `.env` loaded automatically;
- user accounts and private workspaces: sign-in, sessions, password reset, backend ownership checks on every
  project route, two-user isolation tests;
- persistent run history;
- dashboard redesign with Simple and Developer modes.

Stretch, not done:
- context selective/token-budgeted views (§3.4).

## 1. Goal
Deliver a **runnable platform skeleton** where stub agents for every future capability exchange validated messages over RabbitMQ, task state lives in Postgres, artifacts live in a write-once local filesystem store, the Manager can execute a task graph, the UI shows it live, and an LLM gateway exists. After this sprint a teammate can replace *one stub* and the whole system still runs.

## 2. Inputs
Nothing (first sprint). Uses: research doc, work-distribution, team guide.

## 3. Deliverables

### 3.1 Documents
- `docs/members/1/research.md` — distilled from the existing research doc + the extra decisions in this plan.
- `docs/members/1/design.md` — module diagram, state machines, DB schema, topology, failure table.
- `docs/members/1/eval.md` — test + chaos results.
- `docs/members/_template/` — templates for all other members (research/design/eval/README/core-requests).

### 3.2 Code — **MUST**

| # | Work item | Files (under `backend/src/hmap/`) | Notes / acceptance |
|---|---|---|---|
| 1.1 | **Repo bootstrap**: uv project, ruff/mypy/pytest config, Makefile, `.env.example`, `.gitignore` (git itself NOT used by us), `scripts/doctor.sh` | repo root, `scripts/` | `make setup && make doctor` passes |
| 1.2 | **Infra compose**: Postgres16+pgvector, RabbitMQ (mgmt) — official images only; artifacts in `./data/artifacts`; infra-only compose (the app itself runs natively — no deployment, doc 02 §3) | `infra/` | `make infra-up` healthy |
| 1.3 | **Contracts package**: Envelope + all 15 message types (research §8) as Pydantic v2; **all cross-sprint contracts from doc 01 §4 as models** (`RequirementSet`, `TaskGraph`, `ResearchReport`, …); JSON-Schema export; `schema_version` handling (§28) | `core/contracts/` | contract tests validate every example against exported schemas; unknown-field policy; version negotiation |
| 1.4 | **IDs/tracing/errors**: UUID/ULID helpers, `traceparent` inject/extract (W3C), structured JSON logging, error taxonomy (§25) | `core/{ids,tracing,errors}.py` | `error_code` enum + `retryable` classifier |
| 1.5 | **DB schema + migrations**: `projects, documents, tasks, executions, messages, inbox, outbox, events, agents, contexts, artifacts, errors` + unique constraints (§34) | `alembic/versions/001_*.py` | `(task_id,attempt)`, `(artifact_id,version)`, inbox PK enforced |
| 1.6 | **Task state machine** (`CREATED→READY→ASSIGNED→ACCEPTED→RUNNING→RESULT_SUBMITTED→REVIEWING→COMPLETED` + `BLOCKED/CANCELLED/RETRY_SCHEDULED/DEAD_LETTERED/FAILED/NEEDS_REVISION`), guarded transitions with `state_version` CAS (§9, §12, §17) | `manager/task_service.py` | table-driven transition tests; late `started` after `completed` doesn't regress |
| 1.7 | **Bus layer**: RabbitMQ topology — `hmap.commands` (direct, per-capability queues), `hmap.events` (topic), `hmap.retry` (TTL+DLX delayed retry), `hmap.dlx`; publisher confirms; manual ack; bounded prefetch (§22, §27); **in-memory adapter** with same interface | `core/bus/` | same test suite passes on both adapters |
| 1.8 | **Outbox publisher + inbox dedup** (§22, §24) | `core/bus/{outbox,inbox}.py` | crash-between-commit-and-publish test; duplicate delivery test |
| 1.9 | **Registry service**: register, heartbeat, lease, expire, capability+capacity match (§19–21) | `services/registry/` | stale lease → OFFLINE; matching tests |
| 1.10 | **Context service**: immutable versioned snapshots, pinned refs (§13–14). *Selective views + token-budgeted views are STRETCH (§3.4).* | `services/context/` | `CTX@v` pinned in `task.assign`; `NEEDS_REBASE` on update |
| 1.11 | **Artifact service** (§15): `ArtifactStore` interface + **`LocalFSArtifactStore`** as the only required backend — files at `<root>/<project_id>/<artifact_id>/v<version>/<sha256>` (`HMAP_ARTIFACT_ROOT`, default `./data/artifacts`), written via temp file + atomic rename, refused if the path exists, then made read-only; metadata row in Postgres `artifacts`; SHA-256 verified on every read; project-scoped read. (MinIO dropped: community edition archived 2026.) Optional `S3ArtifactStore` is stretch | `services/artifact/` | tamper-detection test; overwrite attempt rejected; same test suite passes on an in-memory store |
| 1.12 | **Agent runtime SDK**: `BaseAgent`, capability decorator, lifecycle FSM (§21), registry client, heartbeat loop, idempotent handler wrapper, progress reporting, cooperative cancellation, context/artifact clients | `core/runtime/` | a 15-line agent runs end-to-end |
| 1.13 | **Manager core**: assignment (capability match), `ack` timeout watchdog, retry scheduler w/ backoff+jitter (§23), DLQ handling (§26), cancellation, **naive topological executor for a `TaskGraph`** (extended by M3), human-approval gate state | `manager/` | runs a 6-task graph through stubs |
| 1.14 | **LLM gateway** (must support **role aliasing** `HMAP_ROLE_MAP` so all roles can map to ONE installed model, and a remote `OLLAMA_BASE_URL` for a shared model host — doc 02 §2.2b; plus an optional OpenAI-compatible cloud provider, e.g. Groq, with 429/`retry-after` backoff and local fallback — doc 02 §2.5): `LLMClient.generate(role, messages, schema=…)`; `OllamaProvider`; `FakeLLM`; record/replay cache; structured-output helper (schema → `format` → validate → repair retry); role→model config; concurrency semaphore; token/latency logging per call. **Thinking off by default**: send Ollama `think: false` (per-call opt-in `think=True`) so reasoning models like Qwen 3 don't emit long hidden reasoning that slows calls and breaks `format` JSON. **`classify(state, questions)`** helper for short typed decisions (bool / choice / score → answer + probability), implemented in Sprint 1 as an enum-schema `generate` call on role `classify` (aliased to `fast`); Sprint 11 may back it with Laya with no agent changes. **Replay cache = one file per request** under `samples/llm_cache/<plugin>/<key[:2]>/<key>.json`; key excludes gateway-injected/shared system-prompt text and the resolved model name (doc 02 §2.4) | `core/llm/` | works in all 4 modes (doc 02 §2.4); changing the shared preamble does not invalidate any member's cache |
| 1.14b | **Cloud key pool** (doc 02 §2.5): providers Groq + Gemini (OpenAI-compatible), comma-separated key lists `HMAP_GROQ_API_KEYS` / `HMAP_GEMINI_API_KEYS`, `HMAP_CLOUD_ROLE_MAP` (role → ordered `provider:model` list), key rotation, per-key cooldown on 429/`retry-after`, disable on auth error, fallback to the local model, usage logged by key fingerprint, `cloud_ok` project flag | `core/llm/` | works with 0, 1 or many keys; no key ever appears in logs, cache or artifacts |
| 1.15 | **FastAPI app**: `/projects`, `/documents` (upload → artifact), `/tasks`, `/agents`, `/events`, `/approvals`; WebSocket `/ws/events` fed from the events exchange; member routers are **mounted automatically** from plug-ins (1.18) | `api/` | OpenAPI served; WS reconnect-safe (snapshot + stream) |
| 1.16 | **Stub agents** for all 8 capabilities returning contract-valid canned output (+ `echo`), packaged as a low-priority plug-in that **auto-yields** a capability once a real plug-in provides it | `agents/stubs/` | full stub pipeline completes a sample project |
| 1.17 | **Frontend shell**: Next.js app, layout, project list, **live event log**, task list/state chips, agents panel (state, heartbeat age); feature panels discovered at build time from `src/features/*/index.ts` (1.18) | `frontend/` | opens against API; shows stub pipeline live |
| 1.18 | **Plug-in auto-discovery + dev agent host** — see §3.5. Agents, API routers, Manager hooks and UI panels are picked up from each member's own folder, so **no member edits a shared file**. `hmap-agents run --all` hosts every discovered agent in **one process** for development | `core/plugins.py`, `core/runtime/host.py`, `frontend/scripts/gen-features.mjs` | adding a new agent folder makes it register, route and show in the UI — with zero edits outside that folder |
| 1.19 | **Tests**: unit, contract, integration against the **`dev` compose stack** (`make infra-up`; tests marked `integration`, skipped with a clear message if the stack is down — no testcontainers), and **7 chaos/failure scenarios**: agent crash mid-task, duplicate message, result-after-timeout, broker restart, manager restart (outbox replay), out-of-order, retry→DLQ | `tests/core/`, `tests/e2e/` | all green via `make infra-up && make test` |
| 1.20 | **Handoff kit**: `scripts/{check_sprint,make_handoff,seed,demo_sprint_1}.sh`, `CONTRIBUTING.md`, `HANDOFF.md`, `samples/` skeleton, member doc templates | repo root | doc 03 §2 procedure works |

### 3.3 Explicitly NOT in Sprint 1 — re-homed so every later member gets something important
| Item | New owner |
|---|---|
| OpenTelemetry + Jaeger + Prometheus/Grafana (§29), DLQ replay UI, load/soak tests (§36) | **Member 4, Sprint 4** |
| **All security incl. the basic layer** (was item 1.18): per-agent service tokens, capability→allowed-message policy table, input size/schema limits, audit log; plus TLS, token rotation, prompt-injection regression suite, audit review, mTLS evaluation (§30). Sprint 1 leaves a no-op `core/policy.py` hook (`allow_all`) that M6 fills in | **Member 6, Sprint 6** |
| One-command laptop demo packaging (`make demo`, seed/reset) | **Member 9, Sprint 9** — there is **no production deployment** (doc 02 §3) |
| Redis cache/rate-limit | optional, Member 11 if needed |
| gRPC / A2A / Kafka | not planned |
| LangGraph as a platform dependency | not required — optional per agent (doc 01 §3) |

### 3.4 STRETCH
- Context service **selective views** and **token-budgeted views** (`context.resolve_view`, §13–14). Until then agents receive the full pinned snapshot and trim it themselves.

### 3.5 Plug-in auto-discovery (design for item 1.18)

Every member package exposes one module, `hmap/agents/<name>/plugin.py`:

```python
PLUGIN = Plugin(
    name="doc_intel",                       # also the replay-cache folder name
    agents=[DocIntelAgent],                 # BaseAgent subclasses → registered, consumed, heartbeated
    router=router,                          # optional FastAPI APIRouter → mounted at /api/<name>
    manager_hooks=[on_document_uploaded],   # optional: @hook("document.uploaded"), @hook("task.completed", capability=...)
    provides={"executor": None, "recovery": None, "llm_provider": None},  # optional strategy slots (M3, M10, M11)
    priority=100,                           # stubs use 0 → a real plug-in for the same capability wins
)
```

| Concern | How it is discovered | Who no longer edits a shared file |
|---|---|---|
| Agents | `core/plugins.discover()` walks `hmap.agents.*` with `pkgutil` and imports each `plugin.py`; `HMAP_PLUGINS=all|a,b,c` filters | everyone (no registry line) |
| Stub replacement | stub capability is skipped when a higher-priority plug-in declares it; `GET /agents/capabilities` shows which is real vs stub (feeds M10's "no silent stubs" check) | M2–M10 (no deleting stub files) |
| API routers | the API app mounts every `PLUGIN.router` | everyone (no `api/main.py` edit) |
| Manager hooks | Manager subscribes each `manager_hooks` entry to its event; strategy slots replace defaults: `executor` (M3 DAG executor replaces the naive one), `recovery` (M10), `llm_provider` (M11 router) | M2, M3, M5, M6, M10, M11 (no edits under `manager/` or `core/llm/`) |
| UI panels | `frontend/scripts/gen-features.mjs` (runs on `predev`/`prebuild`) scans `src/features/*/index.ts` (each exports `{id, title, route, Panel}`) and writes `src/features/_registry.generated.ts` | everyone (no nav/layout edit) |
| DB migrations | unchanged: each sprint adds its own file `NNN_sprint_<n>_<topic>.py` | — |

**Dev agent host:** `hmap-agents run --all` (or `make agents`) starts every discovered agent as asyncio tasks in **one process** — each keeps its own queue consumer, heartbeat and registry lease, so the bus/registry behaviour is identical. `--only research` runs a single agent in its own process (used by the kill-agent chaos tests and when debugging). There are no per-agent containers at all: the demo also uses the single agent host (doc 02 §3).

## 4. Interfaces handed to Member 2

```text
Capability:  document.extract
Task payload (TaskAssign.context_refs → ctx): project_id, document artifact refs[]
Return:      TaskResult(outcome, artifact_refs=[RequirementSet.json])
Helpers:     ctx.artifacts.get(ref) / .put(bytes, media_type), ctx.llm.generate(role="reasoner", schema=RequirementSet), ctx.llm.classify(state, questions)
Upload flow: POST /documents → artifact → Manager creates task "ingest" → agent with document.extract
```
Member 2 adds `agents/doc_intel/plugin.py` declaring `document.extract`; the stub yields automatically. Nothing outside their folders is edited (including the upload→ingest hook, which is a `manager_hooks` entry in their plug-in).

## 5. Definition of Done (sprint-specific additions to doc 03 §3)
- [x] `make infra-up && make test` green (verified on the demo laptop; first run on a teammate's machine is the real clean-machine test)
- [x] `scripts/demo_sprint_1.sh`: upload dummy doc → stub pipeline runs → UI shows all state changes live
- [x] Kill-agent chaos: task recovers on a new execution; duplicate-message test shows dedup hit
- [x] LLM gateway answers in `live` (Ollama) **and** `replay` modes
- [x] Contracts for M2–M11 exist and validate sample payloads
- [x] A fresh member can follow `CONTRIBUTING.md` and add a trivial agent in <30 min (verify with a dry run) **touching only their own folders** — agent, router, hook and UI panel all appear via auto-discovery
- [x] `make agents` runs all agents in one process; `make test` integration tests run against `make infra-up`

## 6. Risks specific to this sprint
| Risk | Mitigation |
|---|---|
| Scope too big | Must/Stretch table; security moved to Sprint 6, context views to stretch; if still behind, cut order: 1.10 `NEEDS_REBASE` → 1.17 polish (never cut 1.6–1.9, 1.12, 1.13, 1.16, 1.18 discovery) |
| RabbitMQ topology complexity | Keep one exchange per concern, document in `design.md`; in-memory adapter keeps most tests fast |
| Docker not installed | Doc 00 — install before day 1 |
| Over-engineering vs. research doc | Follow §39 "Recommended" only; defer everything else |

## 7. Suggested internal order (days)
1: 1.1–1.5 · 2: 1.6–1.8 · 3: 1.9–1.12 · 4: 1.13–1.14 + 1.18 backend discovery · 5: 1.15–1.17 + 1.18 UI panel generation · 6: 1.19 · 7: 1.20 + handoff dry-run
