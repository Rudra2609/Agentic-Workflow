# Sprint 2 plan of action — Member 2: Document intelligence

Spec: [`docs/sprints/sprint-02-member2-document-intelligence.md`](../../sprints/sprint-02-member2-document-intelligence.md).
Goal: uploaded PDF / DOCX / scanned / image / text documents → a validated, traceable `RequirementSet`, produced by
a real `document.extract` agent that replaces the Sprint-1 stub. Written 2026-10-12.

## 0. Decisions already made

| Topic | Decision | Why |
|---|---|---|
| OCR | **Tesseract locally** (`pytesseract`), and **Gemini vision first** for low-quality pages when team keys are set | Tesseract runs on every teammate's OS; Gemini reads bad scans much better and matches the cloud-first policy (doc 02 §2.5). Without keys, or for a "Keep on this computer" project, OCR stays local |
| Gold data | **Authored by us**: 8–10 course-style documents, rendered to PDF / DOCX / scanned PDF / PNG, hand-labelled | Shareable in the public repo, no copyright questions; we control the edge cases |
| PDF / DOCX libraries | `pdfplumber` (text with positions, tables), `pypdfium2` (page rendering for OCR), `python-docx` | Permissive licences (MIT / Apache / BSD). PyMuPDF (AGPL) and Docling are compared in `research.md` only |
| Extraction | Rule pre-pass + LLM per section-aligned chunk (`role="reasoner"`), then merge | Works the same whether `reasoner` lands on Gemini, Groq (8K tokens/min per key) or local `qwen3.5:9b`; chunk budget ≈ 3K tokens fits all three |
| Traceability | Every item carries a `SourceRef` with a verbatim `quote`; quotes are verified by string match, unverifiable items get low confidence or move to `open_questions` | The spec's main defence against invented requirements |

## 1. Needs from Member 1 (us, before the agent work) — logged in `core-requests.md`

1. **Dependencies** in `backend/pyproject.toml` as an optional extra `doc_intel`: `pdfplumber`, `pypdfium2`,
   `python-docx`, `pytesseract`, `Pillow`. Plus `brew install tesseract` on the demo laptop (one-time, you run it);
   `make doctor` reports it.
2. **Gateway image input** for vision OCR: `ctx.llm.generate(..., images=[png_bytes])`, sent only to Gemini routes;
   replay cache keyed on the image hash; a new optional role `vision` (cloud-only; no local fallback model, the caller
   falls back to Tesseract).
3. **Contract (additive):** `SourceRef.folder: str | None` so a requirement keeps its upload folder (Part A / B / C),
   as `HANDOFF.md` asks. Snapshot re-accepted with `make contracts-snapshot`.
4. No Manager or pipeline changes: the `pipeline` plug-in already creates the extract task and the plan task.

## 2. Phases

### Phase A — Research and design (docs first, short)
- `docs/members/2/research.md`: the spec §3 topics, each with a measured mini-comparison on 2–3 gold documents
  (pdfplumber vs PyMuPDF vs pdfminer speed/accuracy; Tesseract vs Gemini on the scanned docs; rules vs LLM vs hybrid).
- `docs/members/2/design.md`: the pipeline below, data structures, failure modes, prompt list, budgets.
- **Done when:** both docs exist and the design names every module and test.

### Phase B — Gold dataset and evaluation harness (before the extractor, so every change is measured)
- `samples/doc_intel/gold/`: 8–10 documents and their labelled `*.expected.json` (a `RequirementSet` plus the
  expected section tree):
  1. programming assignment (native PDF)
  2. lab manual with numbered steps (DOCX)
  3. rubric-heavy marking scheme with merged cells (PDF tables)
  4. scanned assignment (image-only PDF, 150–200 DPI, slight skew)
  5. phone photo of a handout (PNG)
  6. project brief with constraints and deliverables (DOCX with styles, lists, a table)
  7. messy document: two-column layout, footnotes, a page header/footer to ignore
  8. multi-part assignment as folders `Part A/`, `Part B/`, `Part C/` (three files)
  9. typed goal (`request.txt`, the flow when nobody uploads anything)
  10. (stretch) long 25–30 page spec to test chunking and latency
- `backend/tests/doc_intel/eval/`: precision/recall/F1 per field (requirements, constraints, deliverables, criteria),
  rubric-marks accuracy, marks-sum check, quote-verification rate, OCR character accuracy, latency per page.
  Matching is fuzzy (normalised text + token overlap) and documented.
- **Done when:** `uv run python -m tests.doc_intel.eval` prints the results table (the stub scores ~0 as a baseline).

### Phase C — Loading and structure (items 2.1–2.3)
- `loaders/`: PDF (native text with positions), DOCX (styles → headings, lists, tables), TXT/MD, PNG/JPEG,
  image-only PDF pages → OCR. Upload types already accepted by the API: pdf, docx, txt, md, png, jpeg.
- **OCR gate** per page: text density (chars per page area) and garbage ratio below a threshold → render with
  `pypdfium2` at 300 DPI → Gemini vision when allowed, else Tesseract (with deskew + confidence). Native PDFs must
  never trigger OCR (test).
- `structure/`: blocks → `DocumentModel{pages, blocks[{id, type, text, bbox, page, section_path}], tables}`;
  heading detection (font size/bold for PDF, styles for DOCX, numbering patterns), list detection, header/footer removal.
- `tables/`: pdfplumber tables and DOCX tables → rows; rubric detection (a marks/points column) →
  `EvaluationCriterion` with `max_marks` and `rubric_levels`; merged cells filled down.
- **Done when:** section trees match gold on the samples, rubric tables give the right marks, unit tests pass.

### Phase D — Extraction (items 2.4–2.7)
- `chunking.py`: section-aligned chunks within a token budget (gateway estimate), with overlap of the heading path.
- `extract/rules.py`: must/shall/should/"marks"/"submit"/"deadline" patterns → candidate items with exact spans.
- `extract/llm.py` + prompts: one schema-constrained call per chunk (`temperature` 0–0.1), the rule candidates passed
  in as hints; the model must quote its source. Prompts versioned (`prompt_version`) so the replay cache stays valid.
- `merge.py`: dedup (normalised text + token overlap; embedding similarity via local `embed` as a tie-breaker),
  stable ids R1.. C1.. D1.. E1.. in document order, conflict and ambiguity → `open_questions`.
- `validate.py`: schema, quote found in source text, no empty items, marks sum = stated total (`total_marks`), every
  requirement has a source; failures → one targeted re-ask, then lower confidence plus an open question.
- **Done when:** valid JSON ≥ 98 % with repair on gold; requirements F1 measured.

### Phase E — Agent, API and events (items 2.8–2.10)
- `agent.py`: `DocIntelAgent(BaseAgent)` for `document.extract` at priority > 0 (the stub stands down). Reads every
  document in `inputs["documents"]` (name, folder, path), reports progress ("Reading page 3 of 12", "Extracting
  section 2 of 5"), caches per chunk hash so a redelivered task doesn't redo LLM work, and returns the
  `requirement-set` artifact plus a `document-model` artifact for the UI. Respects `cloud_ok` automatically (via
  `ctx.llm`).
- `router.py` (auto-mounted at `/api/doc_intel/…`, ownership checked with `owned_project`):
  `GET /projects/{id}/requirements` (latest, or `?version=`), `PUT` for human edits → new artifact version (author,
  time, diff), `GET /projects/{id}/document-model`.
- Emits `project.requirements_ready {project_id, requirement_set_ref}` for the UI and Member 3.
- **Done when:** upload → RequirementSet → plan task starts, on the in-memory bus and on RabbitMQ + Postgres.

### Phase F — UI panel (item 2.11)
- `frontend/src/features/doc_intel/`: requirements list grouped by type (and by folder for multi-part uploads), with
  confidence badges, inline edit / approve / delete, and open questions. Clicking an item opens the document view with
  its source highlighted (page image or text block). Simple mode shows the list; Developer mode adds spans, chunk and
  model info. Uses the existing design tokens and light/dark themes.
- **Done when:** frontend lint, typecheck and tests pass; manual check in the browser with a screenshot.

### Phase G — Evaluation, demo and handoff (items 2.12–2.14, DoD)
- Record the replay cache on the gold set in `record` mode into `samples/llm_cache/doc_intel/`, once with the cloud
  default and once local-only, and report both (cloud vs local F1 and latency) in `eval.md`. Targets: requirements
  F1 ≥ 0.75, rubric marks accuracy ≥ 0.9 on structured tables, native PDFs never OCR'd.
- Tests: unit (loaders, OCR gate, structure, tables, rules, merge, validate), contract (artifact validates against
  the `RequirementSet` JSON Schema), replay determinism, plug-in conformance, ≥ 1 integration test over
  RabbitMQ + Postgres, Sprint-1 suite unchanged.
- `scripts/demo_sprint_2.sh`: upload the gold documents → requirements visible with source highlights (replay mode,
  no keys or Ollama needed; a `--live` flag uses the real models).
- `docs/members/2/README.md`, `eval.md`; `HANDOFF.md` updated for Member 3 (interface: `RequirementSet`,
  `project.requirements_ready`, guarantees in spec §7).
- **Done when:** `scripts/check_sprint.sh 2` passes, then Docker/Ollama are stopped and you get the handoff note.

## 3. Order and rough effort

| Order | Phase | Effort |
|---|---|---|
| 1 | Member-1 prerequisites (deps, `SourceRef.folder`, gateway images) | small–medium |
| 2 | A research + design | medium |
| 3 | B gold set + eval harness | medium |
| 4 | C loaders, OCR, structure, tables | large |
| 5 | D chunking, rules, LLM extraction, merge, validate | large |
| 6 | E agent, API, events | medium |
| 7 | F UI panel | medium |
| 8 | G recording, eval numbers, demo, docs, `check_sprint.sh 2` | medium |

## 4. Risks to watch

| Risk | Mitigation |
|---|---|
| Gemini free-tier OCR quota or 503s | Per page fallback to Tesseract; OCR results cached by page hash |
| Groq's 8K tokens/min per key on large chunks | Chunk budget ≈ 3K tokens; the router skips to the next provider on "request too large" |
| Model invents requirements | Quote required and verified; rule pre-pass; confidence + `open_questions`; human edit UI |
| Rubric tables with merged cells | Fill-down plus a marks-sum check against the stated total; mismatches become open questions |
| Private documents leaving the laptop | "Keep this project on this computer" already forces local LLM and local OCR |
| Sprint-1 regressions | `make precommit` after every phase; ownership check limits edits to Member 2's paths (plus the logged Member-1 requests) |
