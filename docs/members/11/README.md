# Member 11 — Local LLMs, fine-tuning & model routing (+ the final release gate)

Sprint 11 ([spec](../../sprints/sprint-11-member11-local-llm-routing.md), [plan](plan.md)). What was built and where
the evidence is:

| Doc | What |
|---|---|
| [research.md](research.md) | inference engines, quantization, KV-cache memory, benchmarking, routing, LoRA (spec §3) |
| [model-choice.md](model-choice.md) | the §0 bake-off that chose `qwen3.5:9b` / `qwen3.5:4b` (Sprint 2 prep) |
| [design.md](design.md) | how the plug-in works: registry, hardware, backends, scheduler, router, benchmark, fine-tune |
| [eval.md](eval.md) | the numbers: memory predictions, the benchmark table, the model-size study, the router vs the role maps, LoRA |
| [sizing.md](sizing.md) | which tier on which laptop (16 GB presenter laptop, 8 GB teammates) |
| [release.md](release.md) | the final release gate: regression matrix, chaos, clean-copy run, rehearsals, freeze |
| [runbook.md](runbook.md) | start, stop, reset, what to do if X fails (the demo day sheet) |
| [slides.md](slides.md) | the final slides / Q&A pack skeleton (one slide per member) |
| [core-requests.md](core-requests.md) | the changes in other members' code this sprint needed, with sign-off |

## Use it

```bash
make models-pull TIER=1            # or lite / 2; TIER=0 = replay only (no model)
HMAP_ROUTER=on make demo           # the router decides each call; the Models page shows why
make bench                         # the benchmark table, replayed (no model calls)
scripts/demo_sprint_11.sh          # the Sprint 11 demo (offline)
make release-matrix                # the release gate's regression matrix (long)
```

The Models page (`/features/models`) shows the route decisions live, the registry, what fits on this machine, the
benchmark and the fine-tune result. `HMAP_ROUTER=on` is the default (chosen by the live evaluation, eval.md §4);
`HMAP_ROUTER=off` keeps the role maps exactly as before Sprint 11.
