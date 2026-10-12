# Member 1 — Communication layer, Manager core, platform skeleton

| Document | Content |
|---|---|
| [research.md](research.md) | concepts, alternatives, decisions, sources |
| [design.md](design.md) | modules, state machines, topology, database schema, failure handling |
| [eval.md](eval.md) | test suite, failure scenarios, measured numbers |

## What it provides to Members 2–11
- **Contracts** (`backend/src/hmap/core/contracts/`): the 15 message types, domain events and every cross-member handoff
  type (`RequirementSet`, `TaskGraph`, … `ReviewReport`), exported as JSON Schemas in `backend/src/hmap/core/contracts/schemas/`.
- **Agent runtime**: subclass `BaseAgent`, declare capabilities, implement `handle()`; registration, heartbeats,
  dedup, progress, cancellation, retries are handled for you (`CONTRIBUTING.md` §3).
- **Plug-ins**: `hmap/agents/<name>/plugin.py` is discovered automatically (agents, API router, Manager hooks,
  strategy slots, UI panel).
- **Manager**: task state machine, assignment, retries + dead-letter queue, watchdog, approval gate, DAG executor,
  the default `pipeline` (upload → extract → plan → approval).
- **LLM gateway**: `ctx.llm.generate(role=..., schema=...)`, modes `live | record | replay | fake`, team cloud key pool.
- **API + live UI**: FastAPI at `/api`, WebSocket `/api/ws/events`, Next.js dashboard with a feature-panel slot.
- **Team tooling**: `make precommit`, regression attribution, ownership check, contract snapshot, secret scan,
  handoff snapshots.

## Run
```bash
make setup && make infra-up          # dependencies + Postgres/RabbitMQ
make test                             # all backend tests
scripts/demo_sprint_1.sh              # upload -> stub pipeline -> approval -> completed (over the API)
make api                              # API + Manager + all agents in one process (HMAP_RUN_AGENTS=true)
cd frontend && npm run dev            # dashboard at http://127.0.0.1:3000
```

## Limitations
See `HANDOFF.md` → "Known limitations".
