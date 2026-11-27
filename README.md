# Hierarchical Multi-Agent AI Project Execution Platform (`hmap`)

IT 314 Software Engineering — Group 23.

You give the platform a goal or upload a requirements document. A Manager splits the work into a plan and hands
each step to a specialised AI agent: document intelligence, planning, research, verification, coding, testing,
documentation and final review. The agents talk over a message bus, and a live dashboard shows their progress. Local
LLMs (Ollama, `qwen3.5:9b`) do the work. Everything runs on one laptop; nothing is deployed.

**Status:** Sprints 1–11 are built (communication layer, document intelligence, planning, refinement + observability,
research, verification + security, autonomous coding, automated testing, technical documentation + the one-command
demo, final review + recovery + the end-to-end scenarios, local models + routing + the release gate); Sprints 1–6 are
the code shown at the mid-evaluation. No pipeline step is a stub any more (table below). The release gate's personal
steps (live rehearsals, video, sign-off) are listed in `docs/members/11/release.md`.

## Quick start

The whole platform in one command (needs uv, Node and Docker / Colima). A pre-flight checks the laptop first and
prints the fix for anything missing:

```bash
make demo                    # live: team cloud keys first, local Ollama as fallback — http://127.0.0.1:3000
make demo-replay             # offline: recorded model answers + saved pages (works with Ollama stopped, Wi-Fi off)
make stop                    # stop everything make demo started
make reset-demo              # back to the demo state (empty database, no artifacts); the next make demo seeds again
scripts/demo_chaos.sh        # failure injection: kill the agents mid-research, watch the retry (3 rounds)
```

Demo account: `samples/demo/README.md`. Runbook and troubleshooting: [docs/members/9/platform/](docs/members/9/platform/README.md).

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

## What is real vs stub (after Sprint 11)

| Capability / part | Status | Owner | Notes |
|---|---|---|---|
| Message bus, Manager, state machine, registry, artifacts, LLM gateway, dashboard shell, accounts | **real** | M1 | RabbitMQ + Postgres or in memory; failure recovery (leases, retries, dead letters) |
| `document.extract` (PDF, scanned PDF via OCR, DOCX, text, images) | **real** | M2 | requirements with source spans |
| `plan.generate` / replan, plan approval | **real** | M3 | DAG, coverage matrix, human approval |
| `refine.*` (critique → revise → stop), observability (traces, metrics, Operations / DLQ page) | **real** | M4 | refinement is opt-in per project |
| `research.run` | **real** | M5 | cited reports; offline corpus by default |
| `verify.claims` + follow-up research loop | **real** | M6 | four layers, verdict per claim, one follow-up round |
| Security layer (signed messages, policy table, audit log, limits, key rotation), injection suite | **real** | M6 | `scripts/security_check.sh` |
| `code.implement` + `code.revise` | **real** | M7 | templates, locate → plan → edit → check → debug in a jailed runner; one project head; Coding tab with diff and "Request changes" |
| `test.run` | **real** | M8 | static → build → unit → integration → security → run stages in a Docker sandbox (`make sandbox-image`; local jailed runner without Docker); failures with hints; tests from the criteria when there are none; failed tests → `code.revise` → re-test (≤ 2 rounds); Testing tab |
| `docs.generate` + `docs.update` | **real** | M9 | README, API, architecture (Mermaid), code summaries, report sections from the code's facts (or the verified research); every claim checked against the code, documented examples run in the sandbox, ungrounded sentences removed; docs refreshed after code changes; Docs tab. Also `make demo` / `demo-replay` / `reset-demo` / `report` |
| `review.final` + recovery | **real** | M10 | objective checks first (tests, verified claims, deliverables, docs, constraints), an LLM judge with order swap + votes for the rest; each failure traced to its step; revise / re-run / replan / ask a person through the Manager's `recovery` slot (≤ 2 rounds, plateau and oscillation stops); Review tab with override / accept / request changes. `scripts/demo_final.sh`: the three golden scenarios |
| Model routing / tiers, registry, benchmarks | **real** | M11 | the `llm_provider` router (`HMAP_ROUTER=on` by default; off = the role maps: cloud keys first, local `qwen3.5:9b` fallback): orders each call's routes by key state, recent 429s, prompt size and measured quality, logs why; model registry, memory feasibility, swap-aware scheduler, benchmarks on every member's gold set, LoRA experiment; Models page. `make models-pull TIER=…`, `make bench`, `make release-matrix` |

Stub agents that remain (the `echo` test agent) say so in the dashboard ("placeholder, sample content");
`tests/e2e/test_no_silent_stubs.py` fails when a stub is unflagged or this table disagrees with the code.

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
