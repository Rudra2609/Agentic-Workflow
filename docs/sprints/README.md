# Sprint Overview

> **11 members = 11 sprints.** No extra integration sprint: platform-wide work is spread over Members 4, 6, 9, 10, 11 (table below). Assumption: **1 week per sprint** (change the "Week" column if the team's cadence differs). Strictly sequential: Sprint *N+1* starts when Sprint *N* is accepted.

| Sprint | Week | Owner | Subsystem | Replaces stub | Plugs into | Key output |
|---|---|---|---|---|---|---|
| [01](sprint-01-member1-communication-layer.md) | 1 | **M1** | Communication layer, Manager core, platform skeleton, LLM gateway | — | everything | runnable platform + stubs for all agents |
| [02](sprint-02-member2-document-intelligence.md) | 2 | **M2** | Document ingestion & requirement extraction | `document.extract` | M3 | `RequirementSet` |
| [03](sprint-03-member3-planning-task-decomposition.md) | 3 | **M3** | Roadmap engine & dependency DAG | `plan.generate` | Manager | `TaskGraph` + plan-approval UI |
| [04](sprint-04-member4-self-reflection-refinement.md) | 4 | **M4** | Self-critique & refinement framework | (library) | M2, M3, M5, later all | `Refiner` + `RefinementTrace` |
| [05](sprint-05-member5-autonomous-research.md) | 5 | **M5** | Autonomous research | `research.run` | M6 | `ResearchReport` |
| — | 5→6 | **ALL** | **[MID-EVALUATION](mid-evaluation.md)** (code of M1–M5) | | | live demo |
| [06](sprint-06-member6-research-verification.md) | 6 | **M6** | Research verification | `verify.claims` | M5, M10 | `VerificationReport` |
| [07](sprint-07-member7-autonomous-coding.md) | 7 | **M7** | Coding agent | `code.implement` | M8 | `CodeChangeSet` |
| [08](sprint-08-member8-testing-execution.md) | 8 | **M8** | Testing, sandbox, code refinement | `test.run` | M7, M10 | `TestReport` |
| [09](sprint-09-member9-technical-documentation.md) | 9 | **M9** | Documentation generation | `docs.generate` | M10 | `DocBundle` |
| [10](sprint-10-member10-final-review-recovery.md) | 10 | **M10** | Final review & recovery engine | `review.final` | Manager | `ReviewReport` + recovery loop |
| [11](sprint-11-member11-local-llm-routing.md) | 11 | **M11** | Local LLM infra, routing, benchmarking, LoRA | gateway internals | all agents | Router + registry + benchmarks |

## Dependency chain (why order matters)

```text
M1 ─► M2 ─► M3 ─► M4 ─► M5 ═══ MID-EVAL ═══► M6 ─► M7 ─► M8 ─► M9 ─► M10 ─► M11 ═► RELEASE GATE
│      │     │     │     │
│      │     │     │     └ uses M4 Refiner for synthesis
│      │     │     └ Refiner applied to M2 extraction + M3 plan (measured)
│      │     └ consumes RequirementSet, emits TaskGraph the Manager executes
│      └ first real agent on M1's runtime
└ everything (bus, state, registry, artifacts, LLM gateway, UI shell, stubs)
```

Why this order is also *good* for the mid-eval: after Sprint 5 the product already demonstrates **Plan → Assign → Execute** with real intelligence (documents, planning, refinement, research) over a real distributed bus, while Coding/Testing/Docs/Review are still stubs that keep the pipeline closed-loop.

## Capability stub → real replacement map

| Capability | S1 | After S5 (mid-eval) | Final |
|---|---|---|---|
| `document.extract` | stub | **real (M2)** | real |
| `plan.generate` | stub (linear) | **real (M3)** | real |
| `refine.*` | — | **real (M4)** | real |
| `research.run` | stub | **real (M5)** | real |
| `verify.claims` | stub | stub | real (M6) |
| `code.implement` | stub | stub | real (M7) |
| `test.run` | stub | stub | real (M8) |
| `docs.generate` | stub | stub | real (M9) |
| `review.final` | stub | stub | real (M10) |
| LLM routing | role→model map | role→model map | router (M11) |

## Who owns the platform-wide work (the old "Sprint 12", now distributed)

| Cross-cutting work | Owner | Sprint | Why this member |
|---|---|---|---|
| Bus, state machine, registry, artifacts, Manager core, stubs, thin LLM gateway, **plug-in auto-discovery + dev agent host**, 7 chaos tests | **M1** | 1 | communication layer is their subject |
| Frontend shell + upload/review UI conventions | M1 (minimal) → each member adds a panel | all | every member ships UI for their subsystem |
| **Observability**: OpenTelemetry/Jaeger, Prometheus/Grafana, "why did this task fail" view, **DLQ replay UI**, ops runbook, load/soak test | **M4** | 4 | error classification & traces = their research area; ready before mid-eval |
| **Security (basic + hardening)**: per-agent tokens, capability→message policy, input limits, audit log (moved from Sprint 1), TLS, token rotation, audit review, prompt-injection regression suite (M2/M5/M7/M9 inputs), dependency audit | **M6** | 6 | trust/hallucination/validation mindset |
| **Demo packaging (laptop only, no deployment)**: `make demo` / `make stop` one-command local run, migrations-on-start, seed/reset-to-demo-state, config reference; **platform docs + runbook + final-report compiler** | **M9** | 9 | documentation owner; docs must describe the real way it runs |
| **End-to-end integration**: 3 golden scenarios (incl. human change request), cross-agent contract suite, "no silent stubs" check | **M10** | 10 | final review/recovery closes the loop they must prove |
| **Default-model bake-off** (prep week, before Sprint 2) | **M11** | prep | prompts of M2–M10 are tuned on the model they'll actually ship with |
| **Laptop model setup + FINAL RELEASE GATE**: model tiers + warm-up on the presenter laptop, regression matrix (router on/off × LLM modes), full-stack chaos, clean-copy run on the presenter laptop, offline rehearsal, video, freeze | **M11** | 11 | "running the platform on local LLMs" is their subject |
