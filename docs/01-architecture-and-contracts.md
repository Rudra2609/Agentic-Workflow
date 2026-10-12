# 01 — Architecture, Repo Layout & Cross-Sprint Contracts

Built on the Member-1 research (`Multi_Agent_Communication_Research.md`): manager-led hybrid, **RabbitMQ commands + durable events, PostgreSQL as the authority, immutable content-addressed artifacts (local filesystem store; the research doc's MinIO is replaced because MinIO's community edition was archived in 2026), at-least-once delivery + idempotent consumers**.

## 1. Runtime architecture

```text
 Next.js UI ──HTTP/WS──► FastAPI (manager-api)
                              │
                       Manager / Task State Machine ◄──► PostgreSQL (+pgvector)
                              │  outbox → RabbitMQ  (commands, events, retry, DLX)
          ┌───────────────────┼────────────────────────────────────┐
     doc_intel  planning  research  verify  coding  testing  docgen  review   (all agents run in one host process)
          │            each agent: AgentRuntime SDK (register, heartbeat, ack, progress, artifacts)
          └──► Context svc / Artifact svc (local FS volume) / Registry svc
                              │
                     LLM Gateway (core)  ──►  Ollama on host (:11434)   [Sprint 11: Router + registry + benchmarks]
```

Sandbox execution (Sprint 8) is a **separate** Docker-in-the-host concern — see Sprint 8 for the socket-security trade-off.

## 2. Repository layout (created in Sprint 1)

```text
IT_314_Project_Group23/
├── backend/
│   ├── pyproject.toml            # uv project, python 3.11
│   ├── alembic/                  # DB migrations (append-only; each sprint adds its own migration file)
│   ├── src/hmap/
│   │   ├── core/                 # OWNER: Member 1 (others: read-only)
│   │   │   ├── contracts/        #   Pydantic models + exported JSON Schemas (see §4)
│   │   │   ├── bus/              #   RabbitMQ + in-memory adapters, outbox, inbox
│   │   │   ├── llm/              #   LLMClient, OllamaProvider, FakeLLM, record/replay, structured output
│   │   │   ├── runtime/          #   BaseAgent, lifecycle, registry client, context/artifact clients, dev agent host
│   │   │   ├── plugins.py        #   plug-in discovery (Sprint 1 §3.5)
│   │   │   ├── tracing.py  errors.py  ids.py  policy.py (no-op hook until Sprint 6)  config.py
│   │   ├── manager/              # OWNER: Member 1 only — others extend it through plug-in hooks/strategy slots
│   │   ├── services/             #   registry/ context/ artifact/   (Member 1)
│   │   ├── api/                  #   FastAPI app; mounts every plug-in's router automatically
│   │   └── agents/               # each folder has plugin.py (agents, router, manager hooks, strategy slots)
│   │       ├── stubs/            # Member 1: echo + stub agents so the pipeline runs end-to-end on day 1
│   │       ├── doc_intel/        # Member 2
│   │       ├── planning/         # Member 3
│   │       ├── refine/           # Member 4  (library, not only an agent)
│   │       ├── research/         # Member 5
│   │       ├── verify/           # Member 6
│   │       ├── coding/           # Member 7
│   │       ├── testing/          # Member 8
│   │       ├── docgen/           # Member 9
│   │       ├── review/           # Member 10
│   │       └── models/           # Member 11 (LLM infra / router; replaces core/llm provider wiring)
│   └── tests/{core,doc_intel,planning,refine,research,verify,coding,testing,docgen,review,models,e2e}/
├── frontend/                     # Next.js; src/features/<member-area>/ panels (auto-registered); shell by Member 1
├── infra/
│   ├── docker-compose.yml        # infra only: postgres(+pgvector), rabbitmq; `obs` profile later; sandbox image (Sprint 8)
│   ├── rabbitmq/  postgres/
├── samples/                      # sample PDFs/DOCX, gold datasets, cached research corpora
├── scripts/                      # doctor.sh, make_handoff.sh, demo_*.sh, seed.sh
├── docs/                         # this folder  +  docs/members/<n>/{research.md,design.md,README.md}
├── HANDOFF.md                    # rewritten at the end of every sprint
└── (existing root files: research md, diagrams, work_distribution — left untouched)
```

**Ownership rule:** a member edits only `agents/<theirs>/` (incl. `plugin.py` and their API router), `tests/<theirs>/`, `frontend/src/features/<theirs>/`, `docs/members/<n>/`, `samples/<theirs>/` (+ `samples/llm_cache/<theirs>/`), and their own Alembic migration file. **No shared file is edited by anyone but Member 1**: agents, routers, Manager hooks and UI panels are all picked up by plug-in auto-discovery (Sprint 1 §3.5). Anything under `core/` or `manager/` needs Member 1 sign-off (request via `docs/members/<n>/core-requests.md`).

## 3. Tech stack (pinned in Sprint 1)

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, psycopg3, `aio-pika`, `httpx`, `structlog` |
| Orchestration | Manager = custom task state machine (Sprint 1); RabbitMQ between processes. **LangGraph is optional per agent** (an extra in `pyproject.toml`, e.g. `uv sync --extra coding`); recommended only for Member 7's tool loop. No LangChain dependency in `core/` |
| Data | Postgres 16 + pgvector, RabbitMQ 3.13 (management plugin), artifacts on a local filesystem volume (optional S3 adapter, stretch) |
| LLM | Ollama (OpenAI-compatible `/v1` + native `/api` for `format` schemas) |
| Frontend | Next.js 14/15, TypeScript, Tailwind, React Flow, native WebSocket |
| Quality | pytest + pytest-asyncio, ruff, mypy (core only strict); integration tests run against the `dev` compose stack (`make infra-up`), not testcontainers |
| Observability | structlog JSON logs (Sprint 1), OpenTelemetry + Jaeger + Prometheus/Grafana (Sprint 4, Member 4) |

## 4. Cross-sprint data contracts (the "handoff types")

Defined by Member 1 as Pydantic models in `hmap/core/contracts/` with JSON Schema export. **Fixing these in Sprint 1 lets Members 2–11 start their research and test data now.** Additive changes only (new optional fields ⇒ minor bump, per Member-1 research §28).

| Contract | Producer → Consumer | Key fields |
|---|---|---|
| `Envelope`, `TaskAssign`, `TaskResult`, `Feedback`, `RevisionRequest`, … | Member 1 (all 15 types in research §8) | as in research doc |
| `ArtifactRef` | everyone | `artifact_id, version, uri, sha256, media_type, size_bytes, created_by` |
| `RequirementSet` | M2 → M3 (+M10) | `project_id, source_docs[], requirements[{id,text,type,priority,source_ref{doc,page,span},confidence}], constraints[{id,text,kind}], deliverables[{id,name,format}], evaluation_criteria[{id,criterion,max_marks,rubric_levels[]}], open_questions[]` |
| `TaskGraph` | M3 → Manager (+all agents) | `tasks[{id,title,description,agent_capability,requirement_ids[],acceptance_criteria[],priority,est_effort,phase}], edges[{from,to}], phases[], roadmap, coverage_matrix` |
| `RefinementSpec` / `RefinementTrace` | M4 ↔ any agent | `producer,critic,reviser,stop_policy,iterations[{output_ref,critique,score,issues[{category,severity}]}],stop_reason` |
| `ResearchBrief` → `ResearchReport` | Manager → M5 → M6 | `questions[]` → `claims[{id,text,evidence_ids[]}], evidence[{id,url,quote,content_sha256,retrieved_at}], sources[], coverage, stop_reason` |
| `VerificationReport` | M6 → Manager/M10 | `claim_verdicts[{claim_id, verdict: VERIFIED|UNSUPPORTED|CONFLICTING|NEEDS_MORE_RESEARCH, supporting[], contradicting[], confidence}]` |
| `CodeChangeSet` | M7 → M8/M9/M10 | `task_id, workspace_ref, patch_ref, files_changed[], commands_run[], notes` |
| `TestReport` | M8 → M7/M10 | `stages{static,build,unit,integration,security}{status,output_ref}, failures[{category,file,line,message,hint}], passed, exec_log_ref` |
| `DocBundle` | M9 → M10 | `readme_ref, api_docs_ref, architecture_ref, summaries_ref, accuracy_report{ungrounded_claims[]}` |
| `ReviewReport` | M10 → Manager | `requirement_results[{req_id, PASS|FAIL|PARTIAL, evidence[]}], rubric_scores[], failures[{category,responsible_task_id}], revision_requests[]` |
| `ModelSpec`, `RouteDecision`, `BenchmarkResult` | M11 → all | `role, model, quant, ctx, backend, tok_s, mem_gb, quality_score` |

### Agent plug-in contract (what "an agent" means in this repo)

```python
class BaseAgent:
    capabilities: list[Capability]                       # advertised to the registry
    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult: ...
# AgentContext gives: .llm (LLMClient), .artifacts, .context, .progress(pct, msg), .cancelled (event), .logger
```

A member's deliverable = a `BaseAgent` subclass + `plugin.py` (registers agent, router, hooks) + contracts it needs + tests + API router + UI panel + docs. No registry or compose edit — agents are discovered and all run in one host process.

### LLM Gateway contract (what every agent calls)

```python
resp = await ctx.llm.generate(
    role="reasoner",                 # logical role, NOT a model name: fast | reasoner | coder | judge | embed | classify
    messages=[...],
    schema=MyPydanticModel,          # optional → constrained JSON + validation + retry
    max_tokens=1024, temperature=0.2,
)

# short typed decisions (bool / choice / score) → answers with probabilities
dec = await ctx.llm.classify(state=text, questions=[Choice("category", options={...criteria...})])
```

Agents **never hard-code model names**; several roles may alias to one installed model (`HMAP_ROLE_MAP`, needed because most members can store only one model). Sprint 1 maps roles → models via config; Sprint 11 swaps in routing, benchmarks and fine-tuned adapters with zero agent changes.

## 5. Stub strategy (how sequential works without blocking)

Sprint 1 ships `agents/stubs/` for **every** future capability (`document.extract`, `plan.generate`, `research.run`, `verify.claims`, `code.implement`, `test.run`, `docs.generate`, `review.final`) returning contract-valid canned output. Each member *replaces one stub* simply by adding a plug-in that declares the same capability (stubs have priority 0 and yield automatically); the pipeline never breaks and the Manager is always demo-able.
