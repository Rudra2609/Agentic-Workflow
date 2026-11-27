"""Benchmark harness (items 11.5, 11.6): every model (local and cloud) on the project's own sets.

- :mod:`.quick` — the §0 bake-off sets (88 items: extraction, planning, critique, verify, coding), now through the
  platform gateway so a cloud model and a local one are asked the same way; each model records into its own replay
  root (``samples/llm_cache/models/<model>/``, the cache key does not include the model);
- :mod:`.sets` — every member's gold set, run through that member's own evaluator with the model under test;
- :mod:`.speed` — TTFT, generation / prefill tok/s, cold load, resident memory (local), latency / tokens (cloud);
- :mod:`.table` — results → ``BenchmarkResult`` rows + the router's quality table (``samples/models/bench/table.json``);
- :mod:`.quant` — the quantization study report;
- :mod:`.run` — the command line.
"""
