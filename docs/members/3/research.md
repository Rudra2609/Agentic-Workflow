# Research — Member 3: planning and task decomposition

Spec §3 topics, each with what we took from it and where it shows in the code. Measurements are on our gold set
(`samples/planning/`, [eval.md](eval.md)).

## 1. Hierarchical task networks (HTN) and LLM decomposition
- **HTN planning** (e.g. SHOP2, Nau et al. 2003): a compound task is refined by *methods* into subtasks until only
  primitive tasks remain. The domain knowledge is in the methods, so plans have a predictable shape.
- **LLM decomposition**: least-to-most prompting (Zhou et al. 2023), plan-and-solve prompting (Wang et al. 2023),
  decomposed prompting (Khot et al. 2023), ADaPT — decompose only as needed (Prasad et al. 2024), and
  HuggingGPT / TaskBench, which ask a model for a *task graph* over a fixed set of tools (Shen et al. 2023, 2024).
- **What we did:** a hybrid. The template (`templates.py`) is the HTN "method" for the top two levels
  (research → verify → design → parts → test → document → review); the model only refines each *part* into
  build / test steps, constrained by a JSON schema. That gives every plan the same spine (spec 3.1) and keeps the
  model's job small enough for an 8–9 B local model.

## 2. Limits of LLM-only planning
- Valmeekam et al. ("LLMs still can't plan", 2023) and Kambhampati et al. ("LLM-Modulo", 2024): models produce
  plausible but often invalid plans — missing preconditions, cycles, invented actions. The remedy they argue for is
  "LLM proposes, external verifiers decide".
- **Measured here:** on the gold set the cloud model never made a cycle, but it did leave out requirements (R1/R2 of
  the long lab), returned one empty answer (Part A of the three-part upload), and drew a dependency "backwards"
  through the phases that a naive rule would have dropped although it was right (design check before the build).
- **What we did:** the validator (`validate.py`) decides; the model's edges are the *least trusted* source when a
  cycle has to be broken; capabilities come from a whitelist (schema + validator); missing requirements are
  filled in by rules; an empty or failed answer falls back to the rule planner (`report.fallbacks` says so).

## 3. DAG theory
- **Topological order** (Kahn 1962) and **topological generations** = layers of steps that may run in parallel
  (`networkx.topological_generations`).
- **Critical path method** (Kelley & Walker 1959): longest path with effort weights; *slack* = latest start −
  earliest start. Steps on it delay the whole project (`schedule.py`).
- **Transitive reduction** (Aho, Garey & Ullman 1972): drop A→C when A→B→C exists. Same meaning, far fewer drawn
  edges (`validate.reduce`).
- **Cycle breaking**: the minimum feedback arc set is NP-hard; with ≤ 40 nodes we repeatedly find a cycle and drop
  its least trusted edge (model < repair < human < rule < data-flow < template, then the one going backwards
  through the phases). Property tests on random graphs check it always ends in a valid single-sink DAG.

## 4. Prioritisation
- **MoSCoW** (must/should/could/won't) is what Member 2 extracts from the text.
- **WSJF** (SAFe: cost of delay ÷ job size) needs a cost of delay we do not have for course work.
- **Critical-path-first** shortens the makespan when workers are limited.
- **What we did (D10):** a step takes its highest MoSCoW priority (must → high, should → normal, could → low) and
  steps on the critical path go up one level. The Manager already assigns by priority, so the critical path runs
  first. Priorities are always derived (never accumulated over versions). Weighting by rubric marks was dropped:
  requirement ↔ criterion matching is fuzzy and would make priorities hard to explain.

## 5. Roadmaps and effort
- Phases + milestones + parallel groups is the usual roadmap shape (also what the mid-evaluation asks to show).
- Effort: PERT three-point estimates need three guesses per step; LLM estimates are noisy. We use a heuristic per
  phase and requirement count, let the model propose hours, and clamp to 0.5–16 h. The numbers are for ordering
  and the critical path, not promises (stated in the UI).

## 6. Replanning
- Plan repair vs replanning from scratch (Fox et al. 2006, "plan stability"): repair keeps more of the old plan,
  which people (and running agents) prefer.
- **What we did:** finished and running steps are frozen (same id, same content) so the Manager keeps their
  records and results (`Manager.replace_graph`); only unfinished steps change. Feedback goes to the model as a small
  "remove / change / add" edit; without a model it becomes an acceptance criterion, or a change-request step when
  everything has finished; new work after the final review makes the documents and review run again.
  Sprint 10 (scenario 3, "don't use X" mid-run) relies on this.

## 7. Plan validation and metrics
- TaskBench (Shen et al. 2024) scores task graphs by node and edge F1 against a reference. Exact edge F1 punishes
  harmless granularity differences, so we compare *reachability* (A comes before B, transitive closure) between
  steps matched one-to-one by phase + requirement overlap, plus "must-have" dependencies written by hand.
- Graph edit distance was considered and rejected: expensive and hard to explain.

## 8. Executors
- Layer-by-layer (barrier per layer) vs ready-queue / list scheduling: a barrier wastes time when one step in a
  layer is slow. Our executor is a ready-queue (a step starts as soon as its own dependencies are done), creates
  tasks layer by layer, and caps running plan steps per project (`HMAP_PLAN_MAX_PARALLEL`). Resource-aware LLM
  scheduling is Sprint 11's (gateway concurrency today); sandbox limits are Sprint 8's agent slots.

## 9. Tools compared
| Need | Options | Choice |
|---|---|---|
| Graph algorithms | stdlib `graphlib`, `networkx`, `rustworkx` | `networkx` 3.6.1: everything we need (generations, reduction, cycles, paths), pure Python, BSD; graphs are tiny so speed is irrelevant. 3.7 needs Python ≥ 3.12 |
| Property tests | `hypothesis` | random (possibly cyclic) graphs for the repair |
| DAG UI | React Flow (`@xyflow/react`, MIT), custom SVG, dagre (MIT), elkjs (EPL/GPL) | React Flow for pan / zoom / drag-to-connect; our own layered layout with barycenter crossing reduction (≤ 40 nodes; no extra dependency; elkjs's licence ruled it out) |
