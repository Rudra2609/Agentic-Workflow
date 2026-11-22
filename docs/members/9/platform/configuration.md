# Configuration reference

Generated from the code (`Settings.from_env` in `backend/src/hmap/core/config.py`) and the comments in `.env.example` by `uv run python -m hmap.agents.docgen.config_reference`. Do not edit by hand. Set a value in `.env` (git-ignored) or the environment; the environment wins. Keys live only in `.env`.

## research verification + security (Sprint 6, Member 6)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_AGENT_SECRETS` | list | (not set) | HMAP_AGENT_SECRETS 'kid:secret,...' (newest first); empty = dev mode with a per-process seeded secret |
| `HMAP_AGENT_TOKEN_TTL_S` | int | 604800 | lifetime of an agent service token |
| `HMAP_API_WRITE_BURST` |  | 200 |  |
| `HMAP_API_WRITE_RATE` |  | 20 | API write requests per second per client (burst HMAP_API_WRITE_BURST) |
| `HMAP_SECURITY_ENFORCE` | bool | True | deny (not only audit) messages the policy refuses |
| `HMAP_VERIFY_CACHE_DIR` | Path | data/verify_cache | the verifier's own search results (git-ignored) |
| `HMAP_VERIFY_INDEPENDENT` | bool | True | L3/L4: own searches + cross-source check |
| `HMAP_VERIFY_MAX_ROUNDS` | int | 1 | follow-up research rounds after a verification flags claims (0 = never) |

## accounts (sign-in, sessions, password reset)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_ALLOW_REGISTRATION` | bool | True |  |
| `HMAP_COOKIE_SECURE` | bool | False | Secure flag on cookies; true whenever served over HTTPS |
| `HMAP_PUBLIC_URL` | str | http://localhost:3000 | where users open the dashboard (reset links) |
| `HMAP_SESSION_DAYS` | float | 14.0 |  |
| `HMAP_SMTP_FROM` | str | HMAP <no-reply@localhost> |  |
| `HMAP_SMTP_HOST` | str / None | (not set) |  |
| `HMAP_SMTP_PASSWORD` | str / None | (not set) |  |
| `HMAP_SMTP_PORT` | int | 587 |  |
| `HMAP_SMTP_STARTTLS` | bool | True |  |
| `HMAP_SMTP_USERNAME` | str / None | (not set) |  |

## state / artifacts

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_ARTIFACT_ROOT` | Path | data/artifacts |  |
| `HMAP_DATABASE_URL` | str | postgresql+psycopg://hmap:hmap@127.0.0.1:5433/hmap |  |
| `HMAP_STORE` | Literal | memory | memory (tests) / postgres (demo: needs `make infra-up`) |

## message bus

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_BUS` | Literal | memory | memory (tests) / rabbitmq (demo: needs `make infra-up`) |
| `HMAP_RABBITMQ_URL` | str | amqp://hmap:hmap@127.0.0.1:5672/ |  |

## team cloud key pool (runtime only; doc 02 §2.5)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_CLOUD_API_KEY` | str / None | (not set) |  |
| `HMAP_CLOUD_BASE_URL` | str / None | (not set) |  |
| `HMAP_CLOUD_OK` | bool | True | global switch (HMAP_CLOUD_OK); false keeps every call local |
| `HMAP_CLOUD_ROLE_MAP` | dict | {'reasoner': [('gemini', 'gemini-3.6-flash'), ('groq', 'openai/gpt-oss-120b'), ('gemini', 'gemini-3.5-flash')], 'coder': [('groq', 'openai/gpt-oss-120b'), ('gemini', 'gemini-3.6-flash'), ('gemini', 'gemini-3.5-flash')], 'judge': [('groq', 'qwen/qwen3.8-27b'), ('gemini', 'gemini-3.5-flash')], 'fast': [('groq', 'openai/gpt-oss-20b'), ('gemini', 'gemini-3.5-flash-lite')], 'classify': [('groq', 'openai/gpt-oss-20b'), ('gemini', 'gemini-3.5-flash-lite')], 'vision': [('gemini', 'gemini-3.6-flash'), ('gemini', 'gemini-3.5-flash')]} |  |
| `HMAP_GEMINI_API_KEYS` | list | (not set) | comma-separated |
| `HMAP_GEMINI_BASE_URL` | str | https://generativelanguage.googleapis.com/v1beta/openai |  |
| `HMAP_GROQ_API_KEYS` | list | (not set) | comma-separated, one per contributing teammate |
| `HMAP_GROQ_BASE_URL` | str | https://api.groq.com/openai/v1 |  |

## autonomous coding (Sprint 7, Member 7)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_CODING_CMD_TIMEOUT_S` | float | 20.0 | time limit per workspace command |
| `HMAP_CODING_KEEP_WORK` | bool | False | keep workspaces after packaging (debugging) |
| `HMAP_CODING_MAX_DEBUG_ROUNDS` | int | 4 | edit -> check rounds after a failure |
| `HMAP_CODING_MAX_REVISIONS` | int | 3 | code.revise rounds per original task |
| `HMAP_CODING_MAX_STEPS` | int | 12 | model calls per coding task |
| `HMAP_CODING_PROMPT_TOKENS` | int | 5500 | prompt budget per model call |
| `HMAP_CODING_PYTHON` | str / None | (not set) | interpreter for model-written code; unset = data/coding/venv if built, else the base Python |
| `HMAP_CODING_SANDBOX` | Literal | auto | auto = macOS sandbox-exec (no network, no project folder) when present |
| `HMAP_CODING_WORK_DIR` | Path / None | (not set) | per-task workspaces; unset = <tmp>/hmap-coding. Never inside the project folder (.env lives there) |

## technical documentation + laptop demo (Sprint 9, Member 9)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_DEMO_MIN_FREE_GB` | float / None | (not set) | make demo pre-flight free RAM floor |
| `HMAP_DOCGEN_AUTO_UPDATE` | bool | True | code.completed -> docs.update when docs exist |
| `HMAP_DOCGEN_MAX_ROUNDS` | int | 2 | grounding -> fix rounds before the final gate |
| `HMAP_DOCGEN_RUN_EXAMPLES` | bool | True | run documented snippets in the testing sandbox |
| `HMAP_DOCGEN_SUMMARY_LIMIT` | int | 60 | public symbols summarised per run |
| `HMAP_RETRY_DELAYS_S` | tuple[float, ...] / None | (not set) | Manager backoff per retry (HMAP_RETRY_DELAYS_S=5,30,120); unset = the default |

## runtime

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_ENV` | str | dev | dev / demo |
| `HMAP_LOG_JSON` | bool | True |  |
| `HMAP_LOG_LEVEL` | str | INFO |  |

## refinement + observability (Sprint 4, Member 4)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_GRAFANA_PASSWORD` |  | (not set) | Grafana admin password (viewers need none); make obs-up generates one if empty |
| `HMAP_GRAFANA_URL` | str | http://127.0.0.1:3001 | Grafana (links from the Ops page) |
| `HMAP_JAEGER_URL` | str | http://127.0.0.1:16686 | Jaeger UI (links from the Ops page) |
| `HMAP_METRICS_INTERVAL_S` | float | 5.0 | how often the metric gauges are refreshed |
| `HMAP_METRICS_PORT` | int | 9464 | /metrics port of the agents process; 0 = off |
| `HMAP_OTEL_ENDPOINT` | str / None | (not set) | OTLP/HTTP base URL (Jaeger), e.g. http://127.0.0.1:4318; unset = no traces |
| `HMAP_PROMETHEUS_URL` | str | http://127.0.0.1:9090 | Prometheus (alerts, links) |
| `HMAP_REFINE_DEFAULT` | bool | False | new projects check and improve results (refine=true) |

## LLM gateway (doc 02)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_LLM_CACHE_DIR` | Path | samples/llm_cache |  |
| `HMAP_LLM_MAX_CONCURRENCY` | int | 1 |  |
| `HMAP_LLM_MODE` | Literal | replay | live / record / replay / fake |
| `HMAP_LLM_RECORD_MISSING` | frozenset | frozenset() |  |
| `HMAP_OLLAMA_NUM_CTX` | int / None | 8192 | context window per local call (Ollama's own default, 4096, cuts long prompts) |
| `HMAP_ROLE_MAP` | dict | {} |  |
| `OLLAMA_BASE_URL` | str | http://127.0.0.1:11434 |  |

## plug-ins

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_PLAN_MAX_PARALLEL` | int | 4 | graph steps of one project that may run at once |
| `HMAP_PLUGINS` | str | all | all / comma-separated plug-in names |
| `HMAP_STUB_DELAY_S` | float | 0.0 | minimum simulated work per stub step (demos) |

## autonomous research (Sprint 5, Member 5)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_RESEARCH_CACHE_DIR` | Path | data/research_cache | fetched pages + search results (git-ignored) |
| `HMAP_RESEARCH_MAX_FETCH_MB` | float | 5.0 | largest page / PDF fetched |
| `HMAP_RESEARCH_MODE` | Literal | cached | online = live search + fetch (cached on disk); cached = cache + offline corpus only, never the network; local = the local corpus only |
| `HMAP_RESEARCH_PROVIDERS` | tuple | ('wikipedia', 'arxiv', 'ddg', 'local') | search providers in order (HMAP_RESEARCH_PROVIDERS) |
| `HMAP_RESEARCH_RATE_PER_HOST` | float | 1.0 | requests per second per host |

## automated testing & execution (Sprint 8, Member 8)

| Variable | Type | Default | What it does |
|---|---|---|---|
| `HMAP_TESTING_AUTO_REVISE` | bool | True | failed tests -> code.revise -> test again |
| `HMAP_TESTING_CONCURRENCY` | int | 1 | sandbox runs at the same time |
| `HMAP_TESTING_DEP_AUDIT` | Literal | auto | known-vulnerable pinned dependencies (OSV); offline = cached answers only |
| `HMAP_TESTING_FUZZ` | bool | False | fuzz parsing functions with Hypothesis (or per task) |
| `HMAP_TESTING_GENERATE` | bool | True | write tests from the criteria when there are none |
| `HMAP_TESTING_IMAGE` | str | hmap-sandbox-py:1 | sandbox image (make sandbox-image) |
| `HMAP_TESTING_IMAGE_NODE` | str | hmap-sandbox-node:1 | sandbox image for JS/TS projects |
| `HMAP_TESTING_MAX_ROUNDS` | int | 2 | test -> revise rounds per coding step |
| `HMAP_TESTING_MEMORY_MB` | int | 256 | memory per sandbox run (no swap) |
| `HMAP_TESTING_MUTANTS` | int | 20 | mutants per run |
| `HMAP_TESTING_MUTATION` | bool | False | mutation testing after green unit tests (or per task) |
| `HMAP_TESTING_RUNTIME` | str / None | (not set) | docker --runtime, e.g. runsc (gVisor) |
| `HMAP_TESTING_SANDBOX` | Literal | auto | auto = Docker when it answers and the image exists, else the local jailed runner |
| `HMAP_TESTING_STAGE_TIMEOUT_S` | float | 60.0 | time limit per stage |

## Process environment only

Read before `.env` is loaded: set them in the shell, not in `.env`.

| Variable | What it does |
|---|---|
| `HMAP_ENV_FILE` | which env file to read instead of the repository's .env |
| `HMAP_ROOT` | the repository root (default: found from the code's location) |
| `HMAP_RUN_AGENTS` | false = the API process runs no agents (make demo runs them in their own process) |
