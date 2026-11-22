# Architecture: hmap

The hmap repository implements a hierarchical multi‑agent AI execution platform that coordinates agents, tasks, and observability across a single‑process composition root (backend/src/hmap/system.py::system). Core platform services live in hmap.core (e.g., backend/src/hmap/core/config.py::config and backend/src/hmap/core/runtime/base.py::base) and provide settings, error handling, tracing, and the agent plug‑in contract. Agents such as the documentation generator (backend/src/hmap/agents/docgen/model.py::model) and the testing sandbox (backend/src/hmap/agents/testing/sandbox/__init__.py::sandbox) use these contracts, while the manager (hmap.manager) runs the task state machine and graph executor. Persistence is handled by hmap.db (Postgres connection pool and migrations), and observability is provided by hmap.obs (traces and metrics). Supporting tooling in hmaptools (e.g., hmaptools.report::report) enables regression checks, ownership validation, and secret scanning across the 310 modules and 84 HTTP endpoints.

## Components

```mermaid
flowchart LR
  backend_alembic_["backend/alembic/"]
  hmap["hmap"]
  hmap_agents(["hmap.agents"])
  hmap_api["hmap.api"]
  hmap_core(["hmap.core"])
  hmap_db["hmap.db"]
  hmap_manager["hmap.manager"]
  hmap_obs["hmap.obs"]
  hmap_services["hmap.services"]
  hmap_system["hmap.system"]
  infra_observability_grafana_["infra/observability/grafana/"]
  infra_observability_load_(["infra/observability/load/"])
  scripts_(["scripts/"])
  hmaptools["hmaptools"]
  hmaptools_ownership["hmaptools.ownership"]
  hmaptools_pytest_results["hmaptools.pytest_results"]
  hmaptools_regression["hmaptools.regression"]
  hmaptools_report["hmaptools.report"]
  hmaptools_secrets["hmaptools.secrets"]
  hmaptools_tree["hmaptools.tree"]
  backend_alembic_ --> hmap_db
  hmap_agents --> hmap_api
  hmap_agents --> hmap_core
  hmap_agents --> hmap_db
  hmap_agents --> hmap_manager
  hmap_agents --> hmap_obs
  hmap_agents --> hmap_services
  hmap_agents --> hmap_system
  hmap_api --> hmap_core
  hmap_api --> hmap_manager
  hmap_api --> hmap_obs
  hmap_api --> hmap_services
  hmap_api --> hmap_system
  hmap_core --> hmap_db
  hmap_core --> hmap_obs
  hmap_core --> hmap_services
  hmap_manager --> hmap_core
  hmap_manager --> hmap_db
  hmap_manager --> hmap_obs
  hmap_manager --> hmap_services
  hmap_obs --> hmap_core
  hmap_services --> hmap_core
  hmap_services --> hmap_db
  hmap_system --> hmap_core
  hmap_system --> hmap_db
  hmap_system --> hmap_manager
  hmap_system --> hmap_obs
  hmap_system --> hmap_services
  hmaptools_regression --> hmaptools_tree
  hmaptools_report --> hmaptools_ownership
  hmaptools_report --> hmaptools_regression
  hmaptools_report --> hmaptools_tree
  hmaptools_secrets --> hmaptools_tree
  infra_observability_load_ --> hmap_core
  infra_observability_load_ --> hmap_system
  scripts_ --> hmap_core
  scripts_ --> hmaptools_ownership
  scripts_ --> hmaptools_regression
  scripts_ --> hmaptools_report
  scripts_ --> hmaptools_secrets
  scripts_ --> hmaptools_tree
  lib_aio_pika[("aio_pika")]
  hmap_core -.-> lib_aio_pika
  lib_alembic[("alembic")]
  backend_alembic_ -.-> lib_alembic
  hmap_db -.-> lib_alembic
  lib_ddgs[("ddgs")]
  hmap_agents -.-> lib_ddgs
  lib_fastapi[("fastapi")]
  hmap_agents -.-> lib_fastapi
  hmap_api -.-> lib_fastapi
  lib_httpx[("httpx")]
  hmap_agents -.-> lib_httpx
  hmap_core -.-> lib_httpx
  scripts_ -.-> lib_httpx
  lib_networkx[("networkx")]
  hmap_agents -.-> lib_networkx
  lib_pdfplumber[("pdfplumber")]
  hmap_agents -.-> lib_pdfplumber
  lib_prometheus_client[("prometheus_client")]
  hmap_obs -.-> lib_prometheus_client
  lib_protego[("protego")]
  hmap_agents -.-> lib_protego
  lib_psutil[("psutil")]
  hmap_obs -.-> lib_psutil
  infra_observability_load_ -.-> lib_psutil
  lib_psycopg[("psycopg")]
  hmap_core -.-> lib_psycopg
  hmap_db -.-> lib_psycopg
  hmap_manager -.-> lib_psycopg
  hmap_services -.-> lib_psycopg
  lib_pydantic[("pydantic")]
  hmap_agents -.-> lib_pydantic
  hmap_api -.-> lib_pydantic
  hmap_core -.-> lib_pydantic
  hmap_manager -.-> lib_pydantic
  hmap_services -.-> lib_pydantic
  scripts_ -.-> lib_pydantic
  lib_pypdfium2[("pypdfium2")]
  hmap_agents -.-> lib_pypdfium2
  lib_pytesseract[("pytesseract")]
  hmap_agents -.-> lib_pytesseract
  lib_rank_bm25[("rank_bm25")]
  hmap_agents -.-> lib_rank_bm25
  lib_sqlalchemy[("sqlalchemy")]
  backend_alembic_ -.-> lib_sqlalchemy
  hmap_db -.-> lib_sqlalchemy
  lib_structlog[("structlog")]
  hmap_core -.-> lib_structlog
  lib_trafilatura[("trafilatura")]
  hmap_agents -.-> lib_trafilatura
  subgraph infrastructure
    svc_grafana[("grafana")]
    svc_jaeger[("jaeger")]
    svc_postgres[("postgres")]
    svc_prometheus[("prometheus")]
    svc_rabbitmq[("rabbitmq")]
  end
```

| Component | Modules | Lines | What it is |
|---|---|---|---|
| `backend/alembic/` | 1 | 74 | Alembic environment for hmap. |
| `hmap` | 1 | 3 | hmap — hierarchical multi-agent AI project execution platform. |
| `hmap.agents` | 181 | 24074 | hmap package. |
| `hmap.api` | 8 | 1016 | hmap package. |
| `hmap.core` | 46 | 7621 | Platform core (owner: Member 1). Other members import from here but never edit it (doc 01 §2). |
| `hmap.db` | 4 | 524 | Postgres persistence (Sprint 1 item 1.5): connection pool, schema (``tables``) and migrations (``migrate``). |
| `hmap.manager` | 12 | 2348 | Manager core (owner: Member 1): task state machine, task store, assignment, retries, watchdog, graph executor. |
| `hmap.obs` | 3 | 517 | Observability (Member 4, Sprint 4 §5b): traces, metrics, and the helpers the platform calls at a few points. |
| `hmap.services` | 22 | 1500 | hmap package. |
| `hmap.system` | 1 | 190 | Composition root: builds the whole platform in one process. |
| `infra/observability/grafana/` | 1 | 110 | Writes ``dashboards/hmap.json`` (the committed Grafana dashboard, Sprint 4 item 4.17). Edit the panel list here and |
| `infra/observability/load/` | 1 | 169 | Load / soak test (Sprint 4 item 4.20; reused by Member 11's release gate): N projects at once on the stub agents. |
| `scripts/` | 22 | 2944 | Cloud key-pool check (doc 02 §2.5): does every cloud route in the role map still answer, and which keys work? |
| `hmaptools` | 1 | 1 | Team tooling (owner: Member 1): tree manifests, ownership checks, regression attribution. Standard library only. |
| `hmaptools.ownership` | 1 | 75 | Map changed files to owners using ownership.toml and flag edits outside a member's own paths. |
| `hmaptools.pytest_results` | 1 | 33 | Tiny pytest plug-in (no dependencies): writes {nodeid: outcome} to $HMAP_RESULTS_JSON. |
| `hmaptools.regression` | 1 | 165 | Regression attribution: run the same test suite on a BASE tree and on the CURRENT tree and classify every test. |
| `hmaptools.report` | 1 | 131 | Markdown + JSON report for a regression check (attach it to the commit / handoff). |
| `hmaptools.secrets` | 1 | 45 | Secret scan: fail if anything that looks like a real API key / private key is in the project tree. |
| `hmaptools.tree` | 1 | 92 | Snapshot a project tree as {relative_path: sha256} so two folders (or a folder and a git ref) can be compared |

Arrows are imports: `a --> b` means code in `a` imports `b` (every arrow is an import in the code).

## Inside `hmap.agents`

```mermaid
flowchart LR
  hmap_agents["hmap.agents"]
  hmap_agents_coding["hmap.agents.coding"]
  hmap_agents_doc_intel["hmap.agents.doc_intel"]
  hmap_agents_docgen(["hmap.agents.docgen"])
  hmap_agents_ops["hmap.agents.ops"]
  hmap_agents_pipeline["hmap.agents.pipeline"]
  hmap_agents_planning["hmap.agents.planning"]
  hmap_agents_refine["hmap.agents.refine"]
  hmap_agents_research["hmap.agents.research"]
  hmap_agents_stubs["hmap.agents.stubs"]
  hmap_agents_testing(["hmap.agents.testing"])
  hmap_agents_verify["hmap.agents.verify"]
  hmap_agents_coding --> hmap_agents_refine
  hmap_agents_coding --> hmap_agents_research
  hmap_agents_coding --> hmap_agents_stubs
  hmap_agents_docgen --> hmap_agents_coding
  hmap_agents_docgen --> hmap_agents_planning
  hmap_agents_docgen --> hmap_agents_refine
  hmap_agents_docgen --> hmap_agents_research
  hmap_agents_docgen --> hmap_agents_testing
  hmap_agents_refine --> hmap_agents_doc_intel
  hmap_agents_refine --> hmap_agents_planning
  hmap_agents_research --> hmap_agents_doc_intel
  hmap_agents_research --> hmap_agents_refine
  hmap_agents_research --> hmap_agents_stubs
  hmap_agents_testing --> hmap_agents_coding
  hmap_agents_testing --> hmap_agents_refine
  hmap_agents_testing --> hmap_agents_research
  hmap_agents_verify --> hmap_agents_research
  hmap_agents_verify --> hmap_agents_stubs
  subgraph infrastructure
    svc_grafana[("grafana")]
    svc_jaeger[("jaeger")]
    svc_postgres[("postgres")]
    svc_prometheus[("prometheus")]
    svc_rabbitmq[("rabbitmq")]
  end
```

- `hmap.agents`: hmap package.
- `hmap.agents.coding`: Autonomous coding (Member 7, Sprint 7): ``code.implement`` + ``code.revise``. See ``docs/members/7/``.
- `hmap.agents.doc_intel`: Member 2 - document intelligence: uploaded documents -> a traceable RequirementSet (Sprint 2).
- `hmap.agents.docgen`: Technical documentation agent (Member 9, Sprint 9): ``docs.generate`` / ``docs.update``.
- `hmap.agents.ops`: Operations plug-in (Member 4, Sprint 4): explain failures, list dead letters, replay them explicitly.
- `hmap.agents.pipeline`: Default project pipeline (owner: Member 1).
- `hmap.agents.planning`: Member 3 (Sprint 3): planning and task decomposition — RequirementSet -> validated TaskGraph, the layer-parallel
- `hmap.agents.refine`: Self-reflection and refinement library (Member 4, Sprint 4). Public interface (spec §7):
- `hmap.agents.research`: Autonomous research (Member 5, Sprint 5): ``research.run`` -> a cited ``ResearchReport``. Plan:
- `hmap.agents.stubs`: hmap package.
- `hmap.agents.testing`: Member 8: automated testing & execution (Sprint 8). See ``plugin.py``.
- `hmap.agents.verify`: Member 6 (Sprint 6): research verification — ``verify.claims``. See ``docs/members/6/``.

## Inside `hmap.core`

```mermaid
flowchart LR
  hmap_core["hmap.core"]
  hmap_core_bus["hmap.core.bus"]
  hmap_core_config["hmap.core.config"]
  hmap_core_contracts(["hmap.core.contracts"])
  hmap_core_errors["hmap.core.errors"]
  hmap_core_ids["hmap.core.ids"]
  hmap_core_llm["hmap.core.llm"]
  hmap_core_plugins["hmap.core.plugins"]
  hmap_core_policy(["hmap.core.policy"])
  hmap_core_runtime(["hmap.core.runtime"])
  hmap_core_tracing["hmap.core.tracing"]
  hmap_core_bus --> hmap_core_contracts
  hmap_core_contracts --> hmap_core_errors
  hmap_core_contracts --> hmap_core_ids
  hmap_core_contracts --> hmap_core_tracing
  hmap_core_llm --> hmap_core_config
  hmap_core_llm --> hmap_core_contracts
  hmap_core_llm --> hmap_core_errors
  hmap_core_llm --> hmap_core_tracing
  hmap_core_plugins --> hmap_core_contracts
  hmap_core_plugins --> hmap_core_runtime
  hmap_core_policy --> hmap_core_config
  hmap_core_policy --> hmap_core_contracts
  hmap_core_policy --> hmap_core_tracing
  hmap_core_runtime --> hmap_core_bus
  hmap_core_runtime --> hmap_core_config
  hmap_core_runtime --> hmap_core_contracts
  hmap_core_runtime --> hmap_core_errors
  hmap_core_runtime --> hmap_core_ids
  hmap_core_runtime --> hmap_core_llm
  hmap_core_runtime --> hmap_core_plugins
  hmap_core_runtime --> hmap_core_policy
  hmap_core_runtime --> hmap_core_tracing
  subgraph infrastructure
    svc_grafana[("grafana")]
    svc_jaeger[("jaeger")]
    svc_postgres[("postgres")]
    svc_prometheus[("prometheus")]
    svc_rabbitmq[("rabbitmq")]
  end
```

- `hmap.core`: Platform core (owner: Member 1). Other members import from here but never edit it (doc 01 §2).
- `hmap.core.bus`: Message bus (owner: Member 1). See base.py for the interface and semantics.
- `hmap.core.config`: Settings read from the environment (see /.env.example). One place, so nothing reads os.environ ad hoc.
- `hmap.core.contracts`: Cross-process contracts (owner: Member 1). Import from here, e.g. ``from hmap.core.contracts import TaskAssign``.
- `hmap.core.errors`: Error taxonomy (research §25) and the retry classifier (§23).
- `hmap.core.ids`: Identifier helpers.
- `hmap.core.llm`: LLM gateway (doc 01 §4, doc 02 §2). Agents depend only on :class:`LLMClient`; get one with
- `hmap.core.plugins`: Plug-in declaration and discovery (Sprint 1 §3.5). Every member package exposes ``hmap/agents/<name>/plugin.py``
- `hmap.core.policy`: Basic security layer (Sprint 6 item 6.20, owner Member 6; was Sprint 1 item 1.18) and token lifecycle (6.15).
- `hmap.core.runtime`: hmap package.
- `hmap.core.tracing`: W3C ``traceparent`` propagation (research §11) and structured JSON logging.

## Inside `hmap.services`

```mermaid
flowchart LR
  hmap_services["backend/src/hmap/services/__init__.py"]
  hmap_services_accounts["backend/src/hmap/services/accounts/__init__.py"]
  hmap_services_accounts_base["backend/src/hmap/services/accounts/base.py"]
  hmap_services_accounts_mailer["backend/src/hmap/services/accounts/mailer.py"]
  hmap_services_accounts_memory["backend/src/hmap/services/accounts/memory.py"]
  hmap_services_accounts_pg["backend/src/hmap/services/accounts/pg.py"]
  hmap_services_accounts_ratelimit["backend/src/hmap/services/accounts/ratelimit.py"]
  hmap_services_accounts_security["backend/src/hmap/services/accounts/security.py"]
  hmap_services_accounts_service["backend/src/hmap/services/accounts/service.py"]
  hmap_services_artifact["backend/src/hmap/services/artifact/__init__.py"]
  hmap_services_artifact_base["backend/src/hmap/services/artifact/base.py"]
  hmap_services_artifact_local["backend/src/hmap/services/artifact/local.py"]
  hmap_services_artifact_memory["backend/src/hmap/services/artifact/memory.py"]
  hmap_services_artifact_pg_meta["backend/src/hmap/services/artifact/pg_meta.py"]
  hmap_services_context["backend/src/hmap/services/context/__init__.py"]
  hmap_services_context_base["backend/src/hmap/services/context/base.py"]
  hmap_services_context_memory["backend/src/hmap/services/context/memory.py"]
  hmap_services_context_pg["backend/src/hmap/services/context/pg.py"]
  hmap_services_registry["backend/src/hmap/services/registry/__init__.py"]
  hmap_services_registry_base["backend/src/hmap/services/registry/base.py"]
  hmap_services_registry_memory["backend/src/hmap/services/registry/memory.py"]
  hmap_services_registry_pg["backend/src/hmap/services/registry/pg.py"]
  hmap_services_accounts_memory --> hmap_services_accounts_base
  hmap_services_accounts_pg --> hmap_services_accounts_base
  hmap_services_accounts_service --> hmap_services_accounts_base
  hmap_services_accounts_service --> hmap_services_accounts_mailer
  hmap_services_accounts_service --> hmap_services_accounts_ratelimit
  hmap_services_accounts_service --> hmap_services_accounts_security
  hmap_services_artifact_local --> hmap_services_artifact_memory
  hmap_services_context_memory --> hmap_services_context_base
  hmap_services_context_pg --> hmap_services_context_base
  hmap_services_context_pg --> hmap_services_context_memory
  hmap_services_registry_memory --> hmap_services_registry_base
  hmap_services_registry_pg --> hmap_services_registry_base
  hmap_services_registry_pg --> hmap_services_registry_memory
  subgraph infrastructure
    svc_grafana[("grafana")]
    svc_jaeger[("jaeger")]
    svc_postgres[("postgres")]
    svc_prometheus[("prometheus")]
    svc_rabbitmq[("rabbitmq")]
  end
```

- `backend/src/hmap/services/__init__.py`: hmap package.
- `backend/src/hmap/services/accounts/__init__.py`: User accounts: sign-up, sessions, password reset (Member 1).
- `backend/src/hmap/services/accounts/base.py`: User accounts, sessions and password-reset tokens: records + the store interface (memory and Postgres).
- `backend/src/hmap/services/accounts/mailer.py`: Outgoing account email (password reset).
- `backend/src/hmap/services/accounts/memory.py`: In-memory account store (tests and ``HMAP_STORE=memory``; forgets everything on restart).
- `backend/src/hmap/services/accounts/pg.py`: Account store in PostgreSQL (tables ``users``, ``sessions``, ``password_resets`` — migration ``001b``).
- `backend/src/hmap/services/accounts/ratelimit.py`: Small in-process sliding-window rate limiter for login, registration and password-reset requests.
- `backend/src/hmap/services/accounts/security.py`: Password hashing and opaque tokens (standard library only).
- `backend/src/hmap/services/accounts/service.py`: Account use cases: register, sign in/out, sessions, profile, password change and reset, WebSocket tickets.
- `backend/src/hmap/services/artifact/__init__.py`: hmap package.
- `backend/src/hmap/services/artifact/base.py`: Artifact store interface (research §15, Sprint 1 item 1.11). Implementation: ``LocalFSArtifactStore``
- `backend/src/hmap/services/artifact/local.py`: ``LocalFSArtifactStore``: write-once files under ``HMAP_ARTIFACT_ROOT`` (Sprint 1 item 1.11, research §15).
- `backend/src/hmap/services/artifact/memory.py`: In-memory ``ArtifactStore`` (tests, Phase A) plus helpers shared with ``LocalFSArtifactStore``.
- `backend/src/hmap/services/artifact/pg_meta.py`: Artifact metadata in Postgres (Sprint 1 item 1.11, research §15/§18): the ``artifacts`` table, unique
- `backend/src/hmap/services/context/__init__.py`: hmap package.
- `backend/src/hmap/services/context/base.py`: Context service interface (research §13-14, Sprint 1 item 1.10). Immutable versioned snapshots; assignments
- `backend/src/hmap/services/context/memory.py`: In-memory ``ContextStore`` (Sprint 1 item 1.10, research §13-14). Postgres ``contexts`` table in Phase B.
- `backend/src/hmap/services/context/pg.py`: Postgres ``ContextStore`` (Sprint 1 item 1.10; research §13-14) on the ``contexts`` table (PK
- `backend/src/hmap/services/registry/__init__.py`: hmap package.
- `backend/src/hmap/services/registry/base.py`: Agent registry interface (research §19-21, Sprint 1 item 1.9). Manager-owned projection: advisory for
- `backend/src/hmap/services/registry/memory.py`: In-memory agent registry (Sprint 1 item 1.9; research §16, §19-21).
- `backend/src/hmap/services/registry/pg.py`: Postgres agent registry (Sprint 1 item 1.9; research §16, §19-21) on the ``agents`` table. Same behaviour as

## Inside `hmap.manager`

```mermaid
flowchart LR
  hmap_manager["backend/src/hmap/manager/__init__.py"]
  hmap_manager_assignment["backend/src/hmap/manager/assignment.py"]
  hmap_manager_config["backend/src/hmap/manager/config.py"]
  hmap_manager_executor["backend/src/hmap/manager/executor.py"]
  hmap_manager_hooks["backend/src/hmap/manager/hooks.py"]
  hmap_manager_manager["backend/src/hmap/manager/manager.py"]
  hmap_manager_pg_store["backend/src/hmap/manager/pg_store.py"]
  hmap_manager_records["backend/src/hmap/manager/records.py"]
  hmap_manager_retry["backend/src/hmap/manager/retry.py"]
  hmap_manager_store["backend/src/hmap/manager/store.py"]
  hmap_manager_transitions["backend/src/hmap/manager/transitions.py"]
  hmap_manager_watchdog["backend/src/hmap/manager/watchdog.py"]
  hmap_manager --> hmap_manager_config
  hmap_manager --> hmap_manager_executor
  hmap_manager --> hmap_manager_manager
  hmap_manager --> hmap_manager_records
  hmap_manager --> hmap_manager_store
  hmap_manager --> hmap_manager_transitions
  hmap_manager_assignment --> hmap_manager_records
  hmap_manager_executor --> hmap_manager_records
  hmap_manager_manager --> hmap_manager_assignment
  hmap_manager_manager --> hmap_manager_config
  hmap_manager_manager --> hmap_manager_executor
  hmap_manager_manager --> hmap_manager_hooks
  hmap_manager_manager --> hmap_manager_records
  hmap_manager_manager --> hmap_manager_retry
  hmap_manager_manager --> hmap_manager_store
  hmap_manager_manager --> hmap_manager_transitions
  hmap_manager_manager --> hmap_manager_watchdog
  hmap_manager_pg_store --> hmap_manager_records
  hmap_manager_pg_store --> hmap_manager_store
  hmap_manager_retry --> hmap_manager_config
  hmap_manager_store --> hmap_manager_records
  hmap_manager_watchdog --> hmap_manager_assignment
  hmap_manager_watchdog --> hmap_manager_records
  subgraph infrastructure
    svc_grafana[("grafana")]
    svc_jaeger[("jaeger")]
    svc_postgres[("postgres")]
    svc_prometheus[("prometheus")]
    svc_rabbitmq[("rabbitmq")]
  end
```

- `backend/src/hmap/manager/__init__.py`: Manager core (owner: Member 1): task state machine, task store, assignment, retries, watchdog, graph executor.
- `backend/src/hmap/manager/assignment.py`: Agent selection for READY tasks (research §20, §27). Pure functions; the Manager applies the result.
- `backend/src/hmap/manager/config.py`: Manager tunables (research §23 defaults).
- `backend/src/hmap/manager/executor.py`: Graph executor strategy (Sprint 1 item 1.13). Decides which tasks of a project may start, which are blocked, and
- `backend/src/hmap/manager/hooks.py`: Plug-in hook dispatch and strategy-slot resolution (Sprint 1 §3.5).
- `backend/src/hmap/manager/manager.py`: The Manager (Sprint 1 item 1.13): owns task state, assigns work, consumes agent reports, retries, times out,
- `backend/src/hmap/manager/pg_store.py`: Postgres ``TaskStore`` (Sprint 1 items 1.5/1.8; research §17, §18, §22, §34). Same behaviour as
- `backend/src/hmap/manager/records.py`: Manager-owned persistent records (research §34). Mirrors the Postgres tables of item 1.5; the in-memory store
- `backend/src/hmap/manager/retry.py`: Retry policy (research §23, §25, §26): what to do with a failed execution.
- `backend/src/hmap/manager/store.py`: Task store (research §17, §24, §34): projects, tasks, executions, approvals + the outbox, written together.
- `backend/src/hmap/manager/transitions.py`: Task state machine (Sprint 1 item 1.6; research §9, §12, §17, §18).
- `backend/src/hmap/manager/watchdog.py`: Watchdog decisions (research §21, §25, §26, §35): ack timeouts and abandoned executions. Pure functions over

## Inside `hmap.api`

```mermaid
flowchart LR
  hmap_api["backend/src/hmap/api/__init__.py"]
  hmap_api_app["backend/src/hmap/api/app.py"]
  hmap_api_deps["backend/src/hmap/api/deps.py"]
  hmap_api_feed["backend/src/hmap/api/feed.py"]
  hmap_api_routers["backend/src/hmap/api/routers/__init__.py"]
  hmap_api_routers_auth["backend/src/hmap/api/routers/auth.py"]
  hmap_api_routers_projects["backend/src/hmap/api/routers/projects.py"]
  hmap_api_routers_system["backend/src/hmap/api/routers/system.py"]
  hmap_api_app --> hmap_api_deps
  hmap_api_app --> hmap_api_feed
  hmap_api_app --> hmap_api_routers_auth
  hmap_api_app --> hmap_api_routers_projects
  hmap_api_app --> hmap_api_routers_system
  hmap_api_deps --> hmap_api_feed
  hmap_api_routers_auth --> hmap_api_deps
  hmap_api_routers_projects --> hmap_api_deps
  hmap_api_routers_system --> hmap_api_deps
  hmap_api_routers_system --> hmap_api_feed
  subgraph infrastructure
    svc_grafana[("grafana")]
    svc_jaeger[("jaeger")]
    svc_postgres[("postgres")]
    svc_prometheus[("prometheus")]
    svc_rabbitmq[("rabbitmq")]
  end
```

- `backend/src/hmap/api/__init__.py`: hmap package.
- `backend/src/hmap/api/app.py`: FastAPI application (Sprint 1 item 1.15).
- `backend/src/hmap/api/deps.py`: FastAPI dependencies: the running system lives on ``app.state``; the signed-in user comes from the session cookie.
- `backend/src/hmap/api/feed.py`: Live event feed for the UI: subscribes to every domain event (``#``), keeps a bounded history (snapshot for
- `backend/src/hmap/api/routers/__init__.py`: Core API routers (Member 1). Members' routers come from their plug-ins and are mounted at /api/<plugin>.
- `backend/src/hmap/api/routers/auth.py`: Accounts API: register, sign in/out, profile, password change, password reset, WebSocket tickets.
- `backend/src/hmap/api/routers/projects.py`: Projects, runs, documents, plans, approvals, tasks and artifacts (Sprint 1 item 1.15) — all owner-scoped.
- `backend/src/hmap/api/routers/system.py`: Agents, capabilities, events, dead letters, health (Sprint 1 item 1.15) + the live WebSocket.

## Inside `hmap.db`

```mermaid
flowchart LR
  hmap_db["backend/src/hmap/db/__init__.py"]
  hmap_db_database["backend/src/hmap/db/database.py"]
  hmap_db_migrate["backend/src/hmap/db/migrate.py"]
  hmap_db_tables["backend/src/hmap/db/tables.py"]
  hmap_db --> hmap_db_database
  hmap_db --> hmap_db_migrate
  hmap_db_migrate --> hmap_db_database
  subgraph infrastructure
    svc_grafana[("grafana")]
    svc_jaeger[("jaeger")]
    svc_postgres[("postgres")]
    svc_prometheus[("prometheus")]
    svc_rabbitmq[("rabbitmq")]
  end
```

- `backend/src/hmap/db/__init__.py`: Postgres persistence (Sprint 1 item 1.5): connection pool, schema (``tables``) and migrations (``migrate``).
- `backend/src/hmap/db/database.py`: Async Postgres access for the ``pg_*`` stores: URL helpers + a small psycopg 3 connection pool.
- `backend/src/hmap/db/migrate.py`: Programmatic Alembic: migrate on start, and test helpers.
- `backend/src/hmap/db/tables.py`: SQLAlchemy Core table models of the Sprint 1 schema (mirrors ``alembic/versions/001_sprint_1_core.py``).

## Inside `hmap.obs`

```mermaid
flowchart LR
  hmap_obs["backend/src/hmap/obs/__init__.py"]
  hmap_obs_metrics["backend/src/hmap/obs/metrics.py"]
  hmap_obs_telemetry["backend/src/hmap/obs/telemetry.py"]
  hmap_obs --> hmap_obs_metrics
  hmap_obs --> hmap_obs_telemetry
  subgraph infrastructure
    svc_grafana[("grafana")]
    svc_jaeger[("jaeger")]
    svc_postgres[("postgres")]
    svc_prometheus[("prometheus")]
    svc_rabbitmq[("rabbitmq")]
  end
```

- `backend/src/hmap/obs/__init__.py`: Observability (Member 4, Sprint 4 §5b): traces, metrics, and the helpers the platform calls at a few points.
- `backend/src/hmap/obs/metrics.py`: Metrics (Sprint 4 item 4.17, plan D14/D17): Prometheus counters, histograms and gauges in one registry.
- `backend/src/hmap/obs/telemetry.py`: Traces (Sprint 4 item 4.15, plan D11/D13/D17): OpenTelemetry spans exported over OTLP/HTTP to Jaeger v2.

## Libraries

- aio_pika (declared >=9.4): used by `hmap.core`
- alembic (declared >=1.13): used by `backend/alembic/`, `hmap.db`
- ddgs (declared >=9.16,<9.17): used by `hmap.agents`
- fastapi (declared >=0.115): used by `hmap.agents`, `hmap.api`
- httpx (declared >=0.27): used by `hmap.agents`, `hmap.core`, `scripts/`
- networkx (declared ==3.6.1): used by `hmap.agents`
- pdfplumber (declared >=0.11): used by `hmap.agents`
- prometheus_client (declared >=0.26,<0.27): used by `hmap.obs`
- protego (declared >=0.7,<0.8): used by `hmap.agents`
- psutil (declared >=7.2,<8): used by `hmap.obs`, `infra/observability/load/`
- psycopg (declared >=3.2): used by `hmap.core`, `hmap.db`, `hmap.manager`, `hmap.services`
- pydantic (declared >=2.7,<3): used by `hmap.agents`, `hmap.api`, `hmap.core`, `hmap.manager`, `hmap.services`, `scripts/`
- pypdfium2 (declared >=4.30): used by `hmap.agents`
- pytesseract (declared >=0.3.13): used by `hmap.agents`
- rank_bm25 (declared ==0.2.2): used by `hmap.agents`
- sqlalchemy (declared >=2.0): used by `backend/alembic/`, `hmap.db`
- structlog (declared >=24.1): used by `hmap.core`
- trafilatura (declared ==2.2.0): used by `hmap.agents`

## Infrastructure

Docker compose services: `grafana`, `jaeger`, `postgres`, `prometheus`, `rabbitmq`.
