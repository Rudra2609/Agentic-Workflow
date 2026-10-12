# Research — Member 1: Multi-agent communication, context management and the platform core

This is the condensed, decision-focused version of `Multi_Agent_Communication_Research.md` (the full survey, §1–40),
plus the decisions taken while building Sprint 1. Section numbers "§n" refer to that document.

## 1. Problem

Eleven specialised agents (document intelligence, planning, research, coding, testing, …) must cooperate on one
project. They are separate processes that crash, restart, run slowly (local 7–9B models: 10–200 s per call) and
sometimes produce wrong output. The communication layer has to deliver work **reliably** (no lost or duplicated
effects), keep **one authoritative state** per task, move **large context and files without stuffing them into
messages**, and make every failure **explainable afterwards** — all on one 16 GB laptop.

## 2. Concepts (with sources)

| Concept | Meaning for us | Source |
|---|---|---|
| Commands vs events | a command asks one agent to act (`task.assign`); an event reports a fact (`task.completed`) | §10 |
| At-least-once + idempotency | the broker may redeliver; consumers dedupe on `message_id`, so effects happen once | §22, §24; RabbitMQ confirms docs [S4] |
| Transactional outbox | state change and its event commit in one DB transaction; a publisher sends later, so no "committed but never announced" | §22; Kreps, *The Log* |
| Optimistic concurrency (CAS) | `UPDATE … WHERE state_version = ?` — late or duplicate messages cannot regress state | §12, §17 |
| Leases + heartbeats | registration is not health; an agent is OFFLINE when its lease expires | §19–21 |
| Classified retries + DLQ | retry only transient faults, with backoff + jitter and a *new execution id*; exhausted work goes to a dead-letter queue, never replayed blindly | §23, §25, §26 |
| Immutable, versioned context & artifacts | assignments pin `CTX@v`; artifacts are content-addressed (SHA-256) and never overwritten | §13–15 |
| Versioned schemas | `schema_version` major.minor; unknown fields ignored within a major | §28; JSON Schema 2020-12 [S1] |
| Trace context | W3C `traceparent` on every message | §11; W3C Trace Context [S2] |

## 3. Approaches compared

| Decision | Options considered | Chosen | Why |
|---|---|---|---|
| Topology | peer-to-peer, blackboard, pure pipeline, **manager-led hybrid** | manager-led hybrid | one owner of task state = explainable; agents stay simple (§5, §32) |
| Transport | HTTP calls, Redis streams, NATS JetStream, Kafka, gRPC, **RabbitMQ** | RabbitMQ (+ in-memory adapter with identical semantics) | durable queues, manual ack, prefetch, DLX are built in; Kafka/A2A/gRPC are over-scale for 11 agents (§31, [S4–S6]) |
| State authority | broker state, LangGraph checkpoints, **PostgreSQL** | PostgreSQL | transactions + constraints give CAS, unique `(task_id, attempt)`, outbox in one place (§17, §34) |
| Orchestration library | LangGraph / AutoGen / CrewAI as the backbone | **custom state machine**; LangGraph optional inside an agent | those frameworks are in-process workflow tools, not a cross-process reliability layer (§31, [S9–S11]) |
| Artifact store | MinIO (research recommendation), S3, **local filesystem** | local FS, write-once + SHA-256, metadata in Postgres | MinIO's community edition stopped publishing images (Oct 2025) and was archived (Apr 2026); one laptop needs no object store |
| Agent packaging | one container per agent, **one host process for all agents** | single host process (dev and demo) | saves 1–2 GB RAM next to an 8B model; bus semantics unchanged |
| Extensibility | shared registry files edited by everyone, **plug-in auto-discovery** | discovery of `hmap/agents/<name>/plugin.py` | members never edit shared files → clean folder handoffs without git |
| Integration tests | testcontainers, **the dev compose stack** | compose stack (`make infra-up`) | one Docker setup for dev, tests and demo |
| LLM access | each agent calls Ollama directly, **one gateway with logical roles** | gateway: roles, 4 modes (live/record/replay/fake), schema-constrained JSON with repair, per-plug-in replay cache, `think: false` by default, team cloud key pool for selected roles | swap models without touching agents; deterministic tests and demos (doc 02) |

## 4. Chosen design in one paragraph

The Manager owns a guarded task state machine stored in PostgreSQL. Every state change and its domain event commit
together (outbox); a publisher sends commands to per-capability RabbitMQ queues and events to a topic exchange.
Agents run inside a runtime that registers them with a lease, heartbeats, deduplicates deliveries (inbox), reports
`ack → started → progress → result | error`, honours cancellation and never touches the bus or database directly.
Failures are classified: transient ones are retried as new executions with backoff, others fail or block their
dependants; exhausted retries are dead-lettered for a human. A human approval gate sits between plan and execution.
Everything an agent needs comes by reference (pinned context versions, immutable artifacts), and every message carries
a trace id.

## 5. Model choice (pre-Sprint-2 bake-off, `docs/members/11/model-choice.md`)

`qwen3.5:9b` for every chat role (quality 0.833; coding 71 % first try, 83 % after one test-feedback fix),
`qwen3.5:4b` as lite tier, `nomic-embed-text` for embeddings. The team's free-tier Groq/Gemini keys may serve the
`coder` role at runtime with local fallback (doc 02 §2.5).

## 6. Risks and open questions

- Local model speed dominates end-to-end time; demos therefore rely on `replay`.
- In-memory adapters are only for tests; the demo runs on RabbitMQ + PostgreSQL.
- Registration has no explicit acceptance reply yet (agents assume success; the Manager rejects unknown agents' work).
- Security beyond the policy hook is Member 6's Sprint 6 work.

## 7. Sources

1. J. Kreps, "The Log," 2013 — append-only logs and replay.
2. H. Garcia-Molina, K. Salem, "Sagas," 1987 — long-running distributed work.
3. RabbitMQ docs: Consumer Acknowledgements and Publisher Confirms; Consumers [S4, S5].
4. NATS JetStream docs [S6] (compared, not chosen).
5. JSON Schema Draft 2020-12 [S1]; W3C Trace Context [S2]; OpenTelemetry context propagation [S3].
6. LangGraph [S9], AutoGen [S10], CrewAI [S11], MCP [S7], A2A [S8] — scope comparison.
7. M. Kleppmann, *Designing Data-Intensive Applications*, 2017.
8. MinIO community edition status: maintenance mode Dec 2025, archived Apr 2026 (news reports, 2026).
