# Requests to Member 1 (core / shared files)

Anything you need changed outside your own paths (`ownership.toml`): describe it here, Member 1 implements it.

| # | Date | File / area | What and why | Status |
|---|---|---|---|---|
| 1 | 2026-10-12 | `backend/pyproject.toml`, `uv.lock` | Dependencies `pdfplumber`, `pypdfium2`, `python-docx`, `pytesseract`, `Pillow`; dev `reportlab` (gold documents) | done by Member 1 |
| 2 | 2026-10-12 | `core/llm/` (`base.py`, `gateway.py`, `fake.py`, `errors.py`, `providers/`), `core/runtime/host.py`, `core/config.py` | `LLMClient.read_images` (role `vision`, cloud only, cached by image hash, `VisionUnavailable` otherwise; `FakeLLM.on_vision`) for OCR of scans; `vision` route in the default cloud role map | done by Member 1 (+ `tests/core/llm/test_vision.py`) |
| 3 | 2026-10-12 | `core/contracts/domain.py` | Additive `SourceRef.folder` (upload folder per requirement, as `HANDOFF.md` asks); snapshot accepted with `make contracts-snapshot` | done by Member 1 |
| 4 | 2026-10-12 | `frontend/scripts/gen-features.mjs`, `frontend/src/lib/features.ts`, `frontend/tests/genFeatures.test.ts` | Feature ids may contain `_`: folders follow the plug-in names in `ownership.toml` (`doc_intel`); kebab-case only made Member 2's folder impossible | done by Member 1 |
| 5 | 2026-10-12 | `frontend/vitest.config.mts` | Also run tests in `src/features/**` so members keep panel tests in their own folder | done by Member 1 |
| 6 | 2026-10-12 | `backend/tests/api/test_api.py`, `backend/tests/core/runtime/test_discovery.py` | Sprint-1 tests assumed `document.extract` is a stub / used the name `doc_intel` for a fake plug-in; updated (fake plug-in renamed, priority 200) | done by Member 1 |
| 7 | 2026-10-12 | `scripts/demo_sprint_2.sh`, `scripts/demo_sprint_2.py` | Sprint-2 demo (DoD) in Member 1's `scripts/` | done by Member 1 |
| 8 | 2026-10-12 | `core/config.py`, `core/llm/gateway.py`, `.env.example` | `HMAP_OLLAMA_NUM_CTX` (default 8192): Ollama's own 4096 cut long prompts | done by Member 1 |
| 9 | 2026-10-12 | `core/llm/cloud.py`, `core/llm/providers/openai_compat.py` | Gemini rejects `seed` (400), so seeded calls never reached it: not sent to Gemini. Hidden reasoning used up `max_tokens` and cut answers: `reasoning_effort` "none" (Gemini) / "low" (gpt-oss) unless `think=True` | done by Member 1 (+ tests in `test_key_pool.py`) |
| 10 | 2026-10-12 | `scripts/hmaptools/tree.py`, `scripts/doctor.sh`, `frontend/eslint.config.mjs` | Handoff manifests skip `.claude/`, `*.tsbuildinfo`, `next-env.d.ts`; doctor no longer asks for poppler; lint ignores nested `.next/` | done by Member 1 |
