# Member 2 — Document intelligence

Uploaded PDF / DOCX / scanned PDF / photo / text documents (also several at once, in folders) become a traceable
`RequirementSet`: requirements, constraints, deliverables and marking criteria, each with the sentence it came from.

| | |
|---|---|
| Plug-in | `backend/src/hmap/agents/doc_intel/` (priority 100; replaces the `document.extract` stub) |
| Capability | `document.extract` -> `requirement-set` (`RequirementSet`) + `document-model` (`DocumentModel`) |
| Inputs | the uploaded `document` artifacts + `inputs["documents"]` (`name`, `folder`, `path`) |
| Event | `project.requirements_ready {project_id, task_id, requirement_set_ref}` |
| UI panel | `frontend/src/features/doc_intel/` (project tab "Requirements") |
| API | `GET/PUT /api/doc_intel/requirements/{project_id}`, `GET /api/doc_intel/document-model/{project_id}`, `GET /api/doc_intel/pages/{project_id}/{artifact_id}/{page}` |
| Docs | [plan](plan.md) · [research](research.md) · [design](design.md) · [eval](eval.md) · [testing](testing.md) · [requests to Member 1](core-requests.md) |

## Run
```bash
cd backend && uv run pytest tests/doc_intel -q                       # unit, replay, API (+ integration with infra up)
uv run python -m tests.doc_intel.eval.run_eval --mode replay         # scores on the gold set, no network
uv run python -m tests.doc_intel.eval.run_eval --mode record         # live models (cloud first), re-records answers
uv run python ../samples/doc_intel/gold/build_gold.py                # regenerate the gold documents and labels
scripts/demo_sprint_2.sh                                             # demo (replay; add --live for real models)
```
Optional, for OCR without the cloud: `brew install tesseract`.

## Limitations
- Scans without the cloud (no keys, or a "Keep on this computer" project) are read by Tesseract (`brew install
  tesseract`): good on clean text, weaker on ruled tables. Without either, the page is reported, not guessed.
- The recorded answers in `samples/llm_cache/doc_intel/` come from Groq (Gemini's free daily quota ran out on the
  recording day) and hold no vision answers yet; re-record with `--mode record` when Gemini's quota resets.
- The answer cache (OCR pages, chunk answers) lives in the agent's memory, so a restart redoes the model work. That
  is on purpose: cached text must not outlive a deleted project.
- "Confirm" marks a requirement as checked by a person (confidence 1.0, saved as a new version); there is no
  separate approval field in the contract.
- Edits made in the Requirements tab create a new version; a plan that was already generated from the old version
  is not regenerated automatically (use "Run again").
- The gold set is authored by the team and was used during development; real documents will score lower.
- DOCX has no page numbers, so its source view shows the text with the quote highlighted, not a page image.
