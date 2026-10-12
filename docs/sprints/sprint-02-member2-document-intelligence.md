# Sprint 2 — Member 2: Document Intelligence

**Owner:** Member 2 · **Needs:** Sprint 1 accepted · **Unblocks:** Sprint 3 (Planning)
**Replaces stub:** `document.extract` stub (yields automatically) → `agents/doc_intel/` plug-in

## 1. Goal
Turn uploaded PDF / DOCX / scanned documents into a validated, **traceable** `RequirementSet` (requirements, constraints, deliverables, evaluation criteria) using local LLMs, as an agent on M1's bus.

## 2. What is provided by Sprint 1
`BaseAgent`, bus, artifact store (original files), `/documents` upload endpoint, LLM gateway (`role="reasoner"`, schema-constrained output), `RequirementSet` contract, UI shell slot, FakeLLM/replay.

## 3. Research deliverable (`docs/members/2/research.md`)
- PDF parsing: PyMuPDF vs pdfplumber vs pdfminer vs Docling/Unstructured — accuracy, speed, layout handling.
- DOCX: python-docx (styles → headings, tables, lists); fallback via LibreOffice→PDF.
- OCR: Tesseract (+ `ocrmypdf`), PaddleOCR; when to trigger OCR (text-density heuristic per page); quality/DPI.
- Tables: pdfplumber/Camelot, table→markdown/JSON, merged cells, rubric tables.
- Requirement extraction: rule patterns (shall/must/should/“marks”), LLM extraction, hybrid; constraint vs requirement vs deliverable taxonomy; rubric representation (criterion, marks, levels).
- Long documents with small-context local models: section segmentation + map-reduce + dedup/merge.
- Evaluation of extraction (precision/recall/F1 vs gold; marks-sum consistency).

## 4. Design (`docs/members/2/design.md`)

```text
upload → [Loader] PDF/DOCX → pages/blocks (text, bbox, page)
       → [OCR gate] low text density → OCR
       → [Structure] headings/sections, tables, lists → DocumentModel (normalized, with source spans)
       → [Chunker] section-aware chunks within ctx budget
       → [Extractor] rules pre-pass + LLM(schema) per chunk → candidates
       → [Merger] dedup (embedding/lexical), id assignment R1.., conflict flags
       → [Validator] schema, rubric marks sum, every item has source_ref, confidence
       → RequirementSet artifact  (+ DocumentModel artifact for the UI)
```
Key data structures: `DocumentModel{pages[], blocks[{id,type,text,bbox,page,section_path}], tables[]}`; `SourceRef{doc_id,page,block_ids,char_span}`.

## 5. Work items

### MUST
| # | Item | Files (`agents/doc_intel/`) | Acceptance |
|---|---|---|---|
| 2.1 | Loaders: PDF (native), DOCX, image-only PDF → OCR; per-page OCR gating | `loaders/` | 3 doc types parse; OCR only when needed |
| 2.2 | Normalization → `DocumentModel` with headings/sections/tables/lists + source spans | `structure/` | section tree matches gold on samples |
| 2.3 | Table extraction incl. rubric/marking tables | `tables/` | rubric table → `evaluation_criteria[]` with marks |
| 2.4 | Chunker (token-budgeted via gateway’s tokenizer estimate) | `chunking.py` | chunks ≤ budget, section-aligned |
| 2.5 | LLM extraction prompts + Pydantic schemas (requirements / constraints / deliverables / criteria), rule-based pre-pass for “must/shall/marks” | `extract/` | valid JSON ≥ 98 % (with repair) |
| 2.6 | Merge/dedup/ID assignment; confidence; `open_questions` for ambiguity | `merge.py` | duplicates removed; R/C/D/E ids stable |
| 2.7 | Validation (marks sum, source_ref present, no empty items) | `validate.py` | invalid output rejected → retry |
| 2.8 | `DocIntelAgent(BaseAgent)` capability `document.extract`; progress events (“parsing page 3/12”) | `agent.py` | works on bus; idempotent on redelivery |
| 2.9 | Pipeline wiring: **already done by Member 1's `pipeline` plug-in** (`document.uploaded` → `document.extract` task with every uploaded document, names and folders in `inputs["documents"]`; its result → `plan.generate` task). Member 2 only makes `DocIntelAgent` return a `RequirementSet` artifact of type `requirement-set` — do NOT add duplicate hooks | (none) | upload→RequirementSet w/o manual steps; no file under `manager/` edited |
| 2.10 | API: `GET /projects/{id}/requirements`, `PUT` (human edits) with versioning | `router.py` (auto-mounted via `plugin.py`) | edits create new artifact version |
| 2.11 | UI panel: document viewer with highlighted spans; requirement list with inline edit/approve; confidence badges | `frontend/src/features/doc_intel/` | click requirement → jumps to source |
| 2.12 | **Gold dataset**: ≥8 documents (assignment, lab manual, rubric-heavy, scanned, DOCX, messy tables) + hand-labeled JSON | `samples/doc_intel/` | used by eval |
| 2.13 | Evaluation harness: P/R/F1 per field, marks-sum accuracy, latency, OCR accuracy; results table | `tests/doc_intel/eval/` | numbers in `eval.md` |
| 2.14 | Tests: unit (loaders, merger), contract, integration over bus, replay-mode determinism | `tests/doc_intel/` | green |

### STRETCH
Multi-document projects (assignment + rubric merged); handwriting/low-quality scans; language detection; Docling comparison; embedding-based dedup tuning.

## 6. Local-LLM notes
- `role="reasoner"`, temperature 0–0.1, **constrained JSON**; chunk-level extraction then merge (never ask for the whole 30-page doc).
- Record responses in `record` mode on the gold set → reusable test fixtures and Sprint-11 fine-tune data.
- Memory: OCR + model are sequential, not concurrent.

## 7. Interface handed to Member 3
```text
Artifact: RequirementSet.json  (contract in doc 01 §4)
Event:    project.requirements_ready {project_id, requirement_set_ref}
Guarantee: every requirement has id, text, type, priority, source_ref, confidence; evaluation_criteria marks sum is validated;
           open_questions[] lists ambiguities the planner or human should resolve.
```

## 8. Definition of Done (additions)
- [ ] F1 reported on ≥8 gold docs; target (adjustable): requirements F1 ≥ 0.75, rubric marks accuracy ≥ 0.9 on structured tables
- [ ] Scanned PDF works end-to-end; native PDF doesn’t trigger OCR
- [ ] Demo script `demo_sprint_2.sh`: upload → requirements visible in UI w/ source highlights
- [ ] Sprint-1 tests still green

## 9. Risks
| Risk | Mitigation |
|---|---|
| OCR quality on bad scans | DPI upscaling, deskew, report confidence; human edit UI |
| Local model misses/invents requirements | rule pre-pass + “quote required” (extraction must include source span; spans verified by string match) |
| Long docs slow | per-chunk progress, cache by chunk hash |
