# 00 — Prerequisites Checklist (do this BEFORE Sprint 1)

Machine audited on 2026-10-02: **Apple M3, 16 GB unified RAM, 167 GB free on `/Volumes/Tirth_SSD`**.

## A. Tooling status on the current machine

| Tool | Status | Needed for | Action |
|---|---|---|---|
| Python 3.11.9 | present | all backend | OK (pin 3.11) |
| uv | present | Python env + lockfile | OK |
| Node 20.20 + npm | present | Next.js frontend | OK (pnpm optional) |
| git 2.52 | present | local workspaces for coding agent only | OK — **we do not push** |
| psql 14 (Homebrew) | present | debugging only | Compose runs Postgres 16 + pgvector; don't use the brew one as the DB |
| **Docker** | **MISSING** | Local infra (RabbitMQ, Postgres), Sprint 8 sandboxing | Install **Docker Desktop** or **Colima** (`brew install colima docker docker-compose`) |
| **Ollama** | **MISSING** | local LLM inference | `brew install ollama` (runs on host to use Apple Metal GPU) |
| Tesseract OCR | not checked | Sprint 2 OCR | `brew install tesseract poppler` |
| Pandoc / LibreOffice | not checked | DOCX handling fallback (optional) | optional |

> **Every team member needs the same baseline** (Python 3.11, uv, Node 20, Docker, Ollama). Put this list in the team chat on day 0.

## B. Hardware reality check (decides which models we can use)

16 GB unified memory, shared by macOS + Docker + models.

- Usable for models: roughly **8–10 GB** while Docker stack (~3–4 GB) is running.
- Realistic: **one 7–8B model at 4-bit quantization** (~4.5–5.5 GB) loaded at a time, plus a small 3B model or an embedding model.
- Not realistic: 14B+ models, running 2 large models concurrently, full-precision fine-tuning.
- Teammates may have weaker machines (8 GB). The `FakeLLM` / record-replay mode (Sprint 1) lets them develop and run tests with **no model at all**.

## C. Decisions to lock before Sprint 1 (recommended defaults in bold)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Repo structure | monorepo / multi-repo | **Monorepo** — snapshot-handoff is trivial |
| D2 | Python layout | one package vs many | **one `backend/` project, package `hmap`, one subpackage per member** |
| D3 | Message broker | RabbitMQ / Redis / in-memory | **RabbitMQ** (per Member-1 research) + in-memory adapter for tests |
| D4 | DB | Postgres | **Postgres 16 with pgvector** (one DB for state *and* embeddings) |
| D5 | Artifact store | MinIO / local FS / other S3 | **Local filesystem store** (write-once, SHA-256-addressed, Docker volume; metadata in Postgres) behind an `ArtifactStore` interface. **Not MinIO**: its community edition stopped publishing Docker images (Oct 2025), went into maintenance mode (Dec 2025) and was archived (Apr 2026). An S3 adapter is optional stretch for any maintained S3-compatible store |
| D6 | LLM runtime | Ollama / llama.cpp / MLX / cloud | **Ollama on host** (`qwen3.5:9b`) for every role; at runtime every chat role tries the **team cloud key pool** first (Groq + Gemini, doc 02 §2.5) with automatic local fallback; `embed` stays local |
| D7 | Orchestration | custom state machine / LangGraph | **Custom Manager state machine + RabbitMQ between processes; LangGraph optional per agent** (recommended only for M7's coding loop; it is not a cross-process reliability layer — Member-1 research §31) |
| D8 | Structured LLM output | free text / JSON mode | **Ollama `format` = JSON Schema + Pydantic validation + bounded retry** (7B models are unreliable otherwise) |
| D9 | Frontend | Next.js | **Next.js (App Router) + Tailwind + React Flow** for DAGs |
| D10 | Sprint length | 4–7 days | **assume 1 week/sprint** (adjust in `sprints/README.md`) |
| D11 | Who owns Manager / API / UI shell / integration? | see [04-gaps](04-gaps-and-risks.md) | **Member 1 (confirmed: holds the master folder)** — Sprint 1, plus sign-off on `core/`/`manager/` requests and the final release gate with M11 |
| D12 | Mid-eval date | — | **end of Sprint 6 + 2 buffer days** (changed 2026-10-14) |

## D. Accounts / network

- Model downloads need internet once (~5 GB per 7–8B model). **Disk budget depends on tier** (doc 02 §2.2b): Tier 0 = 0 GB, lite ≈ 3.6 GB (`qwen3.5:4b`), Tier 1 ≈ 6.9 GB (default, `qwen3.5:9b`), Tier 2 ≈ 10 GB+ (**one shared model-host machine only**). Models can live on an external disk (`OLLAMA_MODELS`).
- Docker images: ~3 GB.
- Web research (Sprint 5) needs internet at dev time; **demo must work offline** via cached corpora (see Sprint 5/12).
- No paid API keys are required anywhere in the plan. Optional: free-tier Groq/Gemini keys voluntarily contributed by teammates for the runtime cloud roles (doc 02 §2.5) — each person creates their own key; keys go only in `.env`.

## E. Day-0 verification script (Sprint 1 creates `scripts/doctor.sh`)

```bash
python3 --version && uv --version && node --version
docker info >/dev/null && echo "docker ok"
ollama --version && ollama list && curl -s localhost:11434/api/tags | head -c 200   # recent Ollama needed for `think: false`
tesseract --version | head -1
```

## F. Pre-work every member can do in parallel (does NOT violate sequential build)

The build is sequential, but **research is not**. While earlier sprints run, each later member should:

1. Write their research document (deliverable #1 in every sprint file).
2. Study the contracts in [01-architecture-and-contracts.md](01-architecture-and-contracts.md) — their input and output types are already fixed.
3. Prepare their evaluation/gold dataset (e.g., sample PDFs for Member 2, seeded-hallucination claims for Member 6).
4. Install the baseline toolchain and pull the models they'll use.
5. **Member 11 only:** run the quick model bake-off (Sprint 11 §0) and publish the default Tier-1 model **before Sprint 2 starts**, so every member tunes prompts against the final default model.

This removes most of the idle time that a strictly-sequential schedule would otherwise cause.
