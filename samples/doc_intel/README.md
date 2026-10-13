# Document-intelligence samples (Member 2)

- `gold/content.py`: the gold documents, authored for this project (no third-party text). Every sentence that
  must be found carries its label (R requirement, C constraint, D deliverable); mark tables carry the criteria.
- `gold/build_gold.py`: renders them to `gold/docs/` and writes the expected answers to `gold/expected/`.
  Deterministic, so re-running gives the same files:
  `cd backend && uv run python ../samples/doc_intel/gold/build_gold.py`
- `gold/docs/` (10 cases, 12 files):

| Id | What it tests |
|---|---|
| g01_tcp_chat | native PDF: numbered and bulleted lists, marks table, total, footnote |
| g02_lab_manual | DOCX lab manual: styles, numbered steps, marks table |
| g03_rubric | rubric table with merged "Section" cells and level marks |
| g04_scanned | image-only PDF, skewed and speckled (OCR) |
| g05_photo | phone-photo PNG of a handout (OCR) |
| g06_project_brief | DOCX brief: lists, constraints, deliverables table |
| g07_messy | two-column PDF with running header, footer and footnote |
| g08_multipart | three parts in folders: `Part A/` PDF, `Part B/` DOCX, `Part C/` Markdown |
| g09_request | a typed request (`request.txt`) |
| g10_long_lab | two-page lab sheet (two model calls) with requirements as list items under lead-in sentences |

- `eval_results/`: output of `tests/doc_intel/eval/run_eval.py` (`rules`, `record` = cloud, `replay`,
  `live-local`, the last from before the final fixes).
- Recorded model answers for tests and the demo: `samples/llm_cache/doc_intel/` (replay mode).
