# Hierarchical Multi-Agent AI Project Execution Platform (`hmap`)

IT 314 Software Engineering — Group 23.

You give the platform a goal or upload a requirements document. A Manager splits the work into a plan and hands
each step to a specialised AI agent: document intelligence, planning, research, verification, coding, testing,
documentation and final review. The agents talk over a message bus, and a live dashboard shows their progress. Local
LLMs (Ollama, `qwen3.5:9b`) do the work. Everything runs on one laptop; nothing is deployed.

**Status:** Sprint 1 (Member 1: communication layer, Manager, platform skeleton) is done. The other capabilities are
stub agents until their sprints replace them.

## Quick start

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
