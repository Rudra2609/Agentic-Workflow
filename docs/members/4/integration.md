# Integration guide — using refinement in your agent

There are three ways in. Pick one per capability.

| You have | Use |
|---|---|
| A new agent you write (Members 5, 7, 9, …) | `RefinementMixin` (or `@refinable` on `handle`) — below |
| An agent someone else owns, which you must not edit | a `CapabilityAdapter` in **your** plug-in's `Plugin.refiners` (how Member 4 refines Members 2 and 3) |
| Only a loop, without an agent (Members 7, 8) | `Refiner(...)` directly, or just a `StopPolicy` / `ReflectionMemory` |

In all three cases nothing happens unless `task.refine` is true. That flag comes from the project's "Check and
improve results" setting, or from `inputs["refine"]` on a task.

## Dry run for Member 5 (7 lines; executed in `backend/tests/refine/test_dry_run_member5.py`)

```python
class ResearchAgent(RefinementMixin, BaseAgent):                                    # +1
    def refine_setup(self, task, ctx):                                              # +2
        return RefineSetup(artifact_type="research-report", load=json.loads,       # +3
                           critics=[ProgrammaticCritic(check_citations),           # +4
                                    LLMRubricCritic(RESEARCH_RUBRIC)],             # +5
                           reviser=TargetedReviser())                              # +6
    # ...at the end of handle():
        return await self.refine(task, ctx.result([ref]), ctx)                     # +7
```

What you write yourself is your own domain logic, not plumbing:

- `check_citations(output, task_input) -> list[Issue]`: a plain function. Return an `Issue` (category, severity,
  `location` as a JSON pointer such as `/claims/1`, `fix_hint`) for each problem that code can find.
- `RESEARCH_RUBRIC = Rubric(name=…, subject=…, criteria=(Criterion("Q1", "Is every claim supported…?", 1.0,
  "HALLUCINATION"),))`: only what code cannot check.

What you get with `task.refine` on:

- The result's `research-report` is checked: your check first, then the judge model (role `judge`).
- Each problem is labelled with one of 10 kinds and a severity.
- Only the flagged paths are patched. The loop stops on the default policy: score ≥ 0.9, no major issue, plateau,
  budget, or 3 rounds.
- If the best version is better, it is stored as **version 2 of the same artifact**. A `refinement-trace`
  artifact is added to the result.
- `refine.iteration` / `refine.stopped` events appear, and the project's **Refinement** tab shows the rounds.

Same thing as a decorator: `@refinable(lambda agent, task, ctx: RefineSetup(...))` on `handle`.

Useful `RefineSetup` options:

| Option | What it does |
|---|---|
| `stop=` | your own policy, e.g. `any_of(Threshold(0.95), MaxIters(2))` |
| `task_input=` | what the critics check against (sources, the document model) |
| `reflexion=False` | turns off the reflection notes and the strategy change |
| `write=` | your own "store the improved output" function, e.g. update two artifacts |
| `min_gain=` | apply the improved version only if it scored this much higher |
| `subject=` | the word shown in the UI ("report") |

## Refining someone else's capability (no edits to their folder)

```python
# in YOUR plug-in's plugin.py
async def my_setup(task, result, ctx) -> RefineSetup | None:      # None = nothing to refine in this result
    return RefineSetup(artifact_type="report", load=json.loads, critics=[...], reviser=TargetedReviser())

PLUGIN = Plugin(name="mine", ..., refiners={"report.write": CapabilityAdapter(my_setup)})
```

The agent runtime calls the adapter with the owner's `TaskResult` when `task.refine` is true. On any error the
owner's original result is reported. Your adapter's model calls are recorded under your plug-in's replay cache.
Examples: `agents/refine/adapters/extraction.py` and `plan.py`.

## Loops without an agent

```python
from hmap.agents.refine import Refiner, RefineContext, ProgrammaticCritic, TargetedReviser, any_of, TestsPass, MaxIters
result = await Refiner(producer=write_code, critics=[ProgrammaticCritic(run_linter)], reviser=TargetedReviser(),
                       stop=any_of(TestsPass(lambda out: out["tests_ok"]), MaxIters(4))).run(spec, RefineContext(llm=ctx.llm))
result.final_output, result.best_index, result.stop_reason, result.trace
```

- `StopPolicy` objects work alone: `default_policy().check(LoopState(...))` returns a stop reason or `None`, and
  `best_index(scores)` gives the attempt to keep.
- Reflexion: `memory = await ReflectionMemory("code.fix:python", ArtifactMemoryStore(ctx.artifacts, project_id)).load()`,
  then pass `memory=memory` to `Refiner(...)`. Notes from earlier runs are shown to the reviser
  (`memory.remembered()`), and `memory.choose_strategy(history)` moves targeted → full → widen when the same kind of
  problem repeats.

## Rules

- Programmatic checks first. A code finding overrules the judge (see [design](design.md) §3).
- Never put prompts, document text or keys in span attributes or metrics. `hmap.obs.span(name, attrs)` filters
  them, but don't rely on that.
- Record your refine calls with `HMAP_LLM_RECORD_MISSING=<your plugin>` (cloud first), so tests and demos replay
  offline.
