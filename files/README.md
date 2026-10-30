# Hierarchical Multi-Agent AI Project Execution Platform (`hmap`)

IT 314 Software Engineering — Group 23.

You give the platform a goal or upload a requirements document. A Manager splits the work into a plan and hands
each step to a specialised AI agent: document intelligence, planning, research, verification, coding, testing,
documentation and final review. The agents talk over a message bus, and a live dashboard shows their progress. Local
LLMs (Ollama, `qwen3.5:9b`) do the work. Everything runs on one laptop; nothing is deployed.

**Status:** Sprints 1–6 are done (communication layer, document intelligence, planning, refinement + observability,
research, verification + security); this is the code shown at the mid-evaluation. Coding, testing, documentation and
final review are still stub agents until Sprints 7–10 replace them (table below).

## Quick start

The whole platform in one command, offline (recorded model answers, saved research pages; needs uv, Node and Docker /
Colima):

```bash
make demo                    # http://127.0.0.1:3000 — demo account in samples/demo/README.md; make stop to stop
scripts/demo_chaos.sh        # failure injection: kill the agents mid-research, watch the retry (3 rounds)
```

Step by step:

```bash
make doctor                  # checks Python 3.11, uv, Node, Docker, Ollama
make setup                   # backend dependencies (uv)
cp .env.example .env         # local config; API keys go ONLY in .env (never committed)
scripts/demo_sprint_1.sh     # in-memory end-to-end demo, about 10 s, no Docker or model needed
```

Full stack with the dashboard (Postgres + RabbitMQ in Docker):

```bash
make infra-up
HMAP_BUS=rabbitmq HMAP_STORE=postgres HMAP_RUN_AGENTS=false make api
HMAP_BUS=rabbitmq HMAP_STORE=postgres make agents
cd frontend && npm install && npm run dev      # http://localhost:3000
```

`make help` lists every command. Run `make precommit` before committing or handing off.

## What is real vs stub (mid-evaluation, after Sprint 6)

| Capability / part | Status | Owner | Notes |
|---|---|---|---|
| Message bus, Manager, state machine, registry, artifacts, LLM gateway, dashboard shell, accounts | **real** | M1 | RabbitMQ + Postgres or in memory; failure recovery (leases, retries, dead letters) |
| `document.extract` (PDF, scanned PDF via OCR, DOCX, text, images) | **real** | M2 | requirements with source spans |
| `plan.generate` / replan, plan approval | **real** | M3 | DAG, coverage matrix, human approval |
| `refine.*` (critique → revise → stop), observability (traces, metrics, Operations / DLQ page) | **real** | M4 | refinement is opt-in per project |
| `research.run` | **real** | M5 | cited reports; offline corpus by default |
| `verify.claims` + follow-up research loop | **real** | M6 | four layers, verdict per claim, one follow-up round |
| Security layer (signed messages, policy table, audit log, limits, key rotation), injection suite | **real** | M6 | `scripts/security_check.sh` |
| `code.implement` | stub (sample output) | M7 | Sprint 7 |
| `test.run` | stub | M8 | Sprint 8 |
| `docs.generate` | stub | M9 | Sprint 9 (also full demo packaging) |
| `review.final` | stub | M10 | Sprint 10 |
| Model routing / tiers | role → model map (cloud keys first, local `qwen3.5:9b` fallback) | M11 | Sprint 11 router |

Stub steps say so in the dashboard ("placeholder, sample content").

## Layout

| Path | What |
|---|---|
| `backend/` | Python 3.11 (uv): `hmap` package with core (contracts, bus, LLM gateway), Manager, API, agents, tests |
| `frontend/` | Next.js dashboard; each member's panel is in `frontend/src/features/<plugin>/` |
| `infra/` | Docker Compose for Postgres (host port 5433) and RabbitMQ |
| `scripts/` | Demo, seed, doctor, pre-commit, secret scan, ownership, regression and handoff tools |
| `samples/` | Demo inputs, recorded LLM answers (replay cache) and model bake-off data |
| `docs/` | The plan: architecture, LLM strategy, sprint process, one file per sprint, per-member notes |

## Team workflow

- Sprints run one after another, one member each. Read [docs/README.md](docs/README.md), then your file in
  [docs/sprints/](docs/sprints/README.md).
- Change only your own paths ([ownership.toml](ownership.toml)). Ask for core changes in
  `docs/members/<N>/core-requests.md`.
- Never commit secrets. `.env`, `data/` and `logs/` are git-ignored, and `scripts/secret_scan.sh` runs in
  `make precommit`.
