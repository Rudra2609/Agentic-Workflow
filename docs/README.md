# Project Docs — Hierarchical Multi-Agent AI Project Execution Platform

Codename used in code: **`hmap`**.

This folder is the single source of truth for *how we build the project*, sprint by sprint, until the final demo. **There is no deployment: everything runs locally on Member 1's laptop** (doc 02 §3).

## Reading order

| # | Doc | What it answers |
|---|---|---|
| 0 | [00-prerequisites-checklist.md](00-prerequisites-checklist.md) | What must be installed / decided **before** Sprint 1 starts |
| 1 | [01-architecture-and-contracts.md](01-architecture-and-contracts.md) | Repo layout, tech stack, and the **data contracts** every member codes against |
| 2 | [02-local-llm-and-deployment-strategy.md](02-local-llm-and-deployment-strategy.md) | How we use local LLMs during development and how we run the demo on one laptop |
| 3 | [03-sprint-process-and-handoff.md](03-sprint-process-and-handoff.md) | Sequential sprint rules, handoff-folder procedure, Definition of Done |
| 4 | [04-gaps-and-risks.md](04-gaps-and-risks.md) | Things the work-distribution does **not** cover, and risks |
| 5 | [sprints/README.md](sprints/README.md) | Sprint overview + timeline + dependency chain |
| 6 | [sprints/mid-evaluation.md](sprints/mid-evaluation.md) | Mid-evaluation demo (code of Members 1–5) |
| 7 | `sprints/sprint-01 … sprint-11` | The full plan for each sprint (exactly one owner per sprint, 11 members = 11 sprints) |

## One-paragraph summary of the plan

Eleven sprints, strictly sequential, one per member (Members 1–11). There is no extra integration sprint: the platform-wide work (observability, security, one-command demo packaging, end-to-end integration, release gate) is **split across Members 4, 6, 9, 10 and 11** on top of their own subsystems (see the ownership table in [sprints/README.md](sprints/README.md)). After each sprint the repository is a **complete, runnable snapshot**: the next member receives that folder, adds only their own subsystem, and hands it on. The **mid-evaluation happens after Sprint 5**, showing a working vertical slice: *document upload → requirement extraction → task graph → refined autonomous research → live dashboard*, all running on local LLMs (`qwen3.5:9b`; selected roles may use the team's cloud key pool with local fallback) over the Member-1 communication layer.

## Ground rules (apply to every sprint)

1. **No git commits or pushes** are made by the planning/build assistant. Sharing is by copying the folder (see doc 03).
2. Each sprint owner edits **only their own folders** (listed in their sprint file) plus additive, agreed lines in shared registries.
3. Shared contracts (`backend/src/hmap/core/contracts/`) are owned by Member 1; changes are additive and versioned.
4. Every sprint ends with: tests green, demo script works, `HANDOFF.md` written, snapshot folder produced.
