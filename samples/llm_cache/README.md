# LLM replay cache

`HMAP_LLM_MODE=record` calls the model and writes every answer here; `replay` answers from these files only (no
model, no key, deterministic). Layout: `<plugin>/<key[:2]>/<key>.json`, one file per request, so each member's cache
is a plain folder copy and merges never conflict (doc 02 §2.4).

- The key covers role, messages, schema, options and the plug-in's `prompt_version` — **not** the model name or the
  gateway's shared preamble, so swapping a model or editing the preamble does not invalidate anyone's cache.
- Change a prompt → bump `prompt_version` in your plug-in and re-record: `HMAP_LLM_MODE=record` + your demo.
- A replay miss names the plug-in, the key and which ingredient changed.
- Recorded files never contain API keys or request headers (a cloud answer stores only the provider name, e.g. `groq`; tested in `tests/core/llm/test_key_pool.py`).
- Check the live model and the replay path end to end: `scripts/llm_check.sh` (records to a temporary folder).
