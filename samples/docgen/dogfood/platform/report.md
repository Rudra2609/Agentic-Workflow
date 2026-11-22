# Project report

## Overview

The hmap repository implements a hierarchical multi‑agent AI execution platform that coordinates agents, tasks, and observability across a single‑process composition root (backend/src/hmap/system.py::system). Core platform services live in hmap.core (e.g., backend/src/hmap/core/config.py::config and backend/src/hmap/core/runtime/base.py::base) and provide settings, error handling, tracing, and the agent plug‑in contract. Agents such as the documentation generator (backend/src/hmap/agents/docgen/model.py::model) and the testing sandbox (backend/src/hmap/agents/testing/sandbox/__init__.py::sandbox) use these contracts, while the manager (hmap.manager) runs the task state machine and graph executor. Persistence is handled by hmap.db (Postgres connection pool and migrations), and observability is provided by hmap.obs (traces and metrics). Supporting tooling in hmaptools (e.g., hmaptools.report::report) enables regression checks, ownership validation, and secret scanning across the 310 modules and 84 HTTP endpoints.

## Design

| Component | Modules | What it is |
|---|---|---|
| `backend/alembic/` | 1 | Alembic environment for hmap. |
| `hmap` | 1 | hmap — hierarchical multi-agent AI project execution platform. |
| `hmap.agents` | 181 | hmap package. |
| `hmap.api` | 8 | hmap package. |
| `hmap.core` | 46 | Platform core (owner: Member 1). Other members import from here but never edit it (doc 01 §2). |
| `hmap.db` | 4 | Postgres persistence (Sprint 1 item 1.5): connection pool, schema (``tables``) and migrations (``migrate``). |
| `hmap.manager` | 12 | Manager core (owner: Member 1): task state machine, task store, assignment, retries, watchdog, graph executor. |
| `hmap.obs` | 3 | Observability (Member 4, Sprint 4 §5b): traces, metrics, and the helpers the platform calls at a few points. |
| `hmap.services` | 22 | hmap package. |
| `hmap.system` | 1 | Composition root: builds the whole platform in one process. |
| `infra/observability/grafana/` | 1 | Writes ``dashboards/hmap.json`` (the committed Grafana dashboard, Sprint 4 item 4.17). Edit the panel list here and |
| `infra/observability/load/` | 1 | Load / soak test (Sprint 4 item 4.20; reused by Member 11's release gate): N projects at once on the stub agents. |
| `scripts/` | 22 | Cloud key-pool check (doc 02 §2.5): does every cloud route in the role map still answer, and which keys work? |
| `hmaptools` | 1 | Team tooling (owner: Member 1): tree manifests, ownership checks, regression attribution. Standard library only. |
| `hmaptools.ownership` | 1 | Map changed files to owners using ownership.toml and flag edits outside a member's own paths. |
| `hmaptools.pytest_results` | 1 | Tiny pytest plug-in (no dependencies): writes {nodeid: outcome} to $HMAP_RESULTS_JSON. |
| `hmaptools.regression` | 1 | Regression attribution: run the same test suite on a BASE tree and on the CURRENT tree and classify every test. |
| `hmaptools.report` | 1 | Markdown + JSON report for a regression check (attach it to the commit / handoff). |
| `hmaptools.secrets` | 1 | Secret scan: fail if anything that looks like a real API key / private key is in the project tree. |
| `hmaptools.tree` | 1 | Snapshot a project tree as {relative_path: sha256} so two folders (or a folder and a git ref) can be compared |

## Implementation

- `backend/src/hmap/core/contracts/__init__.py`: Cross-process contracts (owner: Member 1).
- `backend/src/hmap/core/config.py`: Settings read from the environment (see /.env.example).
- `backend/src/hmap/core/errors.py`: Error taxonomy (research §25) and the retry classifier (§23).
- `backend/src/hmap/core/tracing.py`: W3C ``traceparent`` propagation (research §11) and structured JSON logging.
- `backend/src/hmap/core/contracts/domain.py`: Cross-sprint "handoff" contracts (doc 01 §4).
- `backend/src/hmap/core/llm/base.py`: LLM gateway interface (doc 01 §4 "LLM Gateway contract", doc 02 §2).
- `backend/src/hmap/core/llm/__init__.py`: LLM gateway (doc 01 §4, doc 02 §2).
- `backend/src/hmap/core/contracts/capabilities.py`: Capability names (routing keys for per-capability queues) and the descriptor agents register with.
- `backend/src/hmap/core/plugins.py`: Plug-in declaration and discovery (Sprint 1 §3.5).
- `backend/src/hmap/core/runtime/base.py`: What "an agent" is (doc 01 §4 "Agent plug-in contract").
- `backend/src/hmap/system.py`: Composition root: builds the whole platform in one process.
- `backend/src/hmap/agents/refine/core.py`: Core abstractions of the refinement library (Sprint 4 item 4.1).
- `backend/src/hmap/agents/research/model.py`: Internal data of the research agent (Sprint 5).
- `backend/src/hmap/agents/coding/workspace.py`: Per-task workspace with a path jail (Sprint 7 item 7.1, ported from ``samples/coding/workspace.py``).
- `backend/src/hmap/api/app.py`: FastAPI application (Sprint 1 item 1.15).
- `backend/src/hmap/core/runtime/discovery.py`: Plug-in discovery (Sprint 1 item 1.18, §3.5).
- `backend/src/hmap/services/artifact/memory.py`: In-memory ``ArtifactStore`` (tests, Phase A) plus helpers shared with ``LocalFSArtifactStore``.
- `backend/src/hmap/agents/docgen/model.py`: Data of the documentation agent (Sprint 9, plan D3, D11): the facts a repository really contains, the claims a document makes, and the trace of one run.
- `backend/src/hmap/agents/testing/model.py`: Artifact types, ids and the testing trace (Sprint 8, plan D12).
- `backend/src/hmap/core/bus/base.py`: Message-bus interface (research §22, §26, §27).
- `backend/src/hmap/agents/testing/sandbox/__init__.py`: Where generated code runs (Sprint 8 items 8.1 / 8.11, plan D1-D4, D11).
- `backend/src/hmap/services/context/memory.py`: In-memory ``ContextStore`` (Sprint 1 item 1.10, research §13-14).
- `backend/src/hmap/agents/refine/stop.py`: Stop policies (Sprint 4 item 4.6, plan D9): when does a refinement loop end?
- `backend/src/hmap/core/ids.py`: Identifier helpers.
- `backend/src/hmap/agents/doc_intel/model.py`: ``DocumentModel``: the normalised view of every uploaded document (spec §4), stored as the ``document-model`` artifact so the UI can show each requirement's source and highlight it.

## Testing

111 test file(s) with 820 test functions.

```bash
pytest
npm run test
```

## How to run

```bash
make demo
make demo-replay
make api
make agents
make test
make check
hmap-agents
npm run dev
npm run build
python infra/observability/load/soak.py
```
