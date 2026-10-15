# Research: local LLMs, quantization, routing and fine-tuning (Member 11, written ahead of Sprint 11)

Sprint 11 turns the gateway's fixed role → model map into local-model infrastructure: a registry, memory
feasibility, benchmarks on our own gold sets, routing, and one measured LoRA experiment. The default model is
already chosen (`docs/members/11/model-choice.md`). Each topic ends with **→ plan**. Working prototypes are in
`samples/models/`: the GGUF reader, the memory calculator and the router simulation.

## 1. Local inference engines
- **llama.cpp** (GGUF format, CPU + Metal/CUDA) underlies **Ollama**, which adds model management, an HTTP API,
  keep-alive and a loaded-model limit.
- **MLX / mlx-lm** (Apple) runs and fine-tunes models natively on Apple Silicon. **vLLM** targets GPU servers with
  PagedAttention (Kwon et al., 2023), which is not useful on a Mac laptop.

**→ plan:** Ollama stays the default backend; `mlx_lm.server` is the second backend (and the path for a LoRA
adapter); llama.cpp server is optional. All sit behind one provider interface (item 11.3).

## 2. Quantization
- Weight-only quantization keeps quality close to 16-bit at 4–5 bits. GPTQ (Frantar et al., 2023) and AWQ (Lin et
  al., 2024) are the GPU formats; GGUF K-quants (Q4_K_M, Q5_K_M, Q8_0) are llama.cpp's.
- Q4_K_M is the common laptop sweet spot. Q8 costs about 2× the memory for a small quality gain. The trade-off must
  be measured on our tasks, not assumed.

**→ plan:**
- Item 11.6: Q4_K_M vs Q8_0 of `qwen3.5:4b` (Q8 4b ≈ the memory of Q4 9b) on the bake-off sets, so "bigger model
  vs better quant" is answered with data.
- The GGUF reader already reports each model's quant type.

## 3. Memory: weights + KV cache
- Memory ≈ weights + KV cache, with KV per token = 2 × layers × KV heads × head size × bytes. Grouped-query
  attention (Ainslie et al., 2023) cuts KV heads, and therefore the cache, by 4–8×.
- **Hybrid models** (attention mixed with linear / state-space layers) keep a KV cache only in their attention
  layers. Qwen 3.5 has attention in every 4th layer, so the classic formula overestimates it by 4×.

**→ plan:**
- `hardware.py` (item 11.2) = the prototype's `memory.py` + live free RAM.
- Prototype result: mean error 0.21 GB over 5 models with no fitted constants (naive formula 0.34 GB; 0.93 GB off
  for qwen3.5:9b). One open gap (4b, +0.5 GB measured) to explain by measuring at several context lengths.

## 4. Benchmarking methodology
- Separate **quality** (task scores by code, never an LLM judge alone) from **speed**: time to first token,
  generation tok/s, prefill tok/s, cold-load time and resident memory.
- Fix seeds and temperature, pin model digests, run on a clean machine, and repeat. Our bake-off speeds were taken
  under swap pressure and must be re-run.

**→ plan:** item 11.5 extends the bake-off harness with every sprint's gold set (M2 F1, M3 validity, M5 coverage,
M6 detection, M7 pass@1, M10 judge κ). Results go to a table per model × quant × role, with digests recorded.

## 5. Routing
- **FrugalGPT** (Chen et al., 2023): an LLM **cascade** (cheap model first, escalate when a scorer is not
  confident) matches the strong model's quality at a fraction of the cost.
- **RouteLLM** (Ong et al., 2024): learned routers trained on preference data choose strong vs weak models per
  query.
- Hybrid LLM (Ding et al., 2024): route by predicted query difficulty.
- On one laptop, **switching models has a cost**: if two models do not fit together, every switch is a cold load
  (4–10 s measured).

**→ plan:**
- Item 11.7: rules first, then a **cascade with self-check escalation** (signals the platform already has: valid
  JSON, acyclic plan, acceptance tests). The decision log records a reason for every call.
- Prototype on the bake-off results (held-out halves): role tables picked from ~10 items per type overfit (worse
  than today). The cascade 4b → 9b reached +0.046 quality at −44 % time, an upper bound because its escalation
  signal was the grading tests. Sprint 11 measures it with separate acceptance tests.
- `HMAP_ROUTER=off` stays the escape hatch.

## 6. Fine-tuning: LoRA / QLoRA and datasets
- **LoRA** (Hu et al., 2022) trains small low-rank adapters. **QLoRA** (Dettmers et al., 2023) trains them on a
  4-bit base, so 1–4B models are trainable on 16 GB.
- **Data quality beats quantity** (LIMA, Zhou et al., 2023). Training on a model's own *verified* outputs is
  rejection-sampling fine-tuning, in the spirit of STaR (Zelikman et al., 2022). It helps only when the model does
  not already rate those outputs as likely.
- Avoid contamination: a strict held-out split, and never train on the evaluation sets.

**→ plan:**
- Items 11.9–11.11: dataset from the record cache filtered by validators / tests, deduped, split by task (not by
  sample).
- The §0 rehearsal (42 accepted solutions, validation loss already 0.31) predicts a small or null gain. Report it
  honestly, and prefer a narrow, measurable skill (e.g. Member 2's JSON extraction).

## 7. Specialist vs generalist
- Our bake-off: the coding specialist `qwen2.5-coder:7b` was **worse** at our coding tasks (28 %) than the
  generalist `qwen3.5:9b` (68 %). Newer generalists often beat older specialists, so every choice must be
  benchmarked.

**→ plan:** keep one generalist for every role unless a benchmark on our own sets says otherwise.

## 8. Hardware sizing (8 / 16 / 24 / 32 GB)
- Budget = RAM − OS and apps − demo stack − headroom; the model gets what is left.
- Prototype table (assumptions to be replaced by item 11.17 measurements):
  - **16 GB:** one 9B model (+ embedder), even at 32k context;
  - **24 GB:** 9B + 4B together, so routing costs no swaps;
  - **8 GB:** no live model next to the demo stack, so use the replay tier.

**→ plan:** `docs/members/11/sizing.md` (item 11.14) from measured numbers on Member 1's laptop.

## References
Kwon et al. 2023 (vLLM / PagedAttention) · Frantar et al. 2023 (GPTQ) · Lin et al. 2024 (AWQ) · Ainslie et al. 2023
(GQA) · Chen, Zaharia & Zou 2023 (FrugalGPT) · Ong et al. 2024 (RouteLLM) · Ding et al. 2024 (Hybrid LLM) · Hu et al.
2022 (LoRA) · Dettmers et al. 2023 (QLoRA) · Zhou et al. 2023 (LIMA) · Zelikman et al. 2022 (STaR) · llama.cpp GGUF
specification · Ollama API documentation (`/api/ps`).
