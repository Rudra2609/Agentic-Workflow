# Testing — Member 2: document intelligence

What is tested, how to run it, and what each test proves. Scores on the gold set are in [eval.md](eval.md).

## 1. How to run
```bash
cd backend
uv run pytest tests/doc_intel -q                    # Member 2's backend tests (integration skips without infra)
make infra-up && uv run pytest tests/doc_intel -q   # ... including the RabbitMQ + Postgres test
uv run pytest tests/core/llm/test_vision.py -q      # the gateway's image input (Member 1 code, made for Sprint 2)
cd ../frontend && npm test -- src/features/doc_intel   # the Requirements panel's logic
cd .. && scripts/check_sprint.sh 2                  # everything: secrets, lint, types, all tests, build, demo x2
```
Nothing needs a network, an API key or Ollama: the model answers are replayed from `samples/llm_cache/doc_intel/`
or scripted with `FakeLLM`. Tesseract is optional; its one test skips when it is not installed.

| What | Count | Where |
|---|---|---|
| Backend tests (Member 2) | 55 (incl. 10 JSON-Schema cases, 1 integration) | `backend/tests/doc_intel/` |
| Gateway tests made for Sprint 2 (Member 1 code) | 6 vision + 4 others | `backend/tests/core/llm/` |
| Frontend tests | 7 | `frontend/src/features/doc_intel/logic.test.ts` |
| Whole project at handoff | 751 backend, 90 frontend | `scripts/check_sprint.sh 2` -> PASS (2026-10-12) |

## 2. The test data
- **Gold documents** (`samples/doc_intel/gold/`): 10 cases written for this project and rendered by
  `build_gold.py`, with the expected answers in `expected/*.json`. See `samples/doc_intel/README.md`.
- **Recorded answers** (`samples/llm_cache/doc_intel/`): the cloud model's answers for every gold part, replayed by
  `HMAP_LLM_MODE=replay`. The replay key covers the prompt, the chunk text and the rule hints, so changing any of
  them needs a re-record: `uv run python -m tests.doc_intel.eval.run_eval --mode record` (team keys in `.env`).

## 3. What each file covers

### `test_loaders.py` — reading files (spec item 2.1) and structure (2.2)
| Test | Proves |
|---|---|
| `test_detect_kind_by_content_not_just_name` | the file type comes from the bytes (`%PDF`, PNG, DOCX zip), not only the name |
| `test_marker_and_line_helpers` | list markers (incl. pdfminer's `(cid:127)` bullet) are stripped; "10 clients" is not a list; hyphenation is undone |
| `test_native_pdf_structure_and_sections` | headings and levels match the gold sections; list items, section paths, boxes, footnote; text offsets are exact; a native PDF is never OCR'd |
| `test_two_column_pdf_reads_columns_in_order_and_drops_furniture` | left column before right; running header/footer and footnote are recognised; a two-line title is one heading |
| `test_docx_styles_lists_and_tables` / `..._rubric_merged_cells_are_repeated` | DOCX styles -> headings, numbering -> list items, tables -> marks / deliverables |
| `test_markdown_parser` / `test_markdown_and_text_files` | headings, lists, wrapped items, pipe tables, code fences; folders kept |
| `test_scanned_pdf_goes_to_ocr_and_vision_markdown_is_parsed` | an image-only page goes to OCR; the vision model's Markdown becomes headings, items and a marks table |
| `test_scan_without_any_ocr_is_reported_not_guessed` | without OCR the page is reported in the warnings, not invented |
| `test_photo_uses_vision_and_caches_it` | a photo is read once; the second read comes from the cache |
| `test_broken_files_become_warnings` | a corrupt PDF / DOCX gives a warning, not a crash |
| `test_tesseract_reads_the_photo` | local OCR works (skips without `tesseract`) |

### `test_tables_chunks.py` — tables (2.3), levels (2.2), chunking (2.4)
| Test | Proves |
|---|---|
| `test_rubric_with_merged_section_cells_and_level_marks` | merged "Section" cells are filled down; level marks "(6)" and ranges "(2-3)"; the Total row |
| `test_marks_deliverables_headerless_and_other_tables` | marks tables with or without a header, deliverables tables, other tables ignored |
| `test_stated_totals` | "Total: 100 marks", "worth 50 marks in total", "out of 30"; "10 % per day" is not a total |
| `test_heading_levels_from_size_and_numbering` | levels from font size, "1.2" one level under "1" |
| `test_chunks_skip_tables_and_furniture_and_respect_the_budget` | headers, footers, footnotes and marks tables never reach the model; a small budget splits at section borders |
| `test_chunks_never_span_documents` | each document is chunked on its own; the folder is in the prompt |

### `test_extract.py` — rules, quotes, the model call, merge, validation (2.5–2.7)
| Test | Proves |
|---|---|
| `test_rule_patterns` | must/should/may -> priority; constraint kinds; sentences split; R / C / D found by section and wording |
| `test_list_under_a_lead_in_becomes_requirements` | "your code needs to support:" is not an item; each list item under it is a requirement |
| `test_quote_location` | exact / approximate / unverified quote lookup, curly quotes and dashes normalised |
| `test_extract_chunk_reasks_for_missing_quotes_and_caches` | an unfound quote triggers one re-ask; the answer is cached; temperature 0, role `reasoner` |
| `test_hints_are_in_the_prompt` | the prompt carries the document name, folder, headings and the rule hints |
| `test_null_fields_fall_back_to_defaults` | a model writing `null` for a field that does not apply is not a failure |
| `test_merge_dedups_orders_and_numbers` | duplicates removed, the more confident kept, one kind per sentence, ids R1.. in document order, full `SourceRef` |
| `test_validation_reports_marks_problems_and_empty_sets` | marks that do not add up, a level above the maximum, an empty set -> questions; the contract refuses a wrong total |

### `test_pipeline.py` — the whole pipeline
| Test | Proves |
|---|---|
| `test_gold_set_in_replay_meets_the_sprint_targets` | **the Sprint-2 targets** on the recorded answers: requirements F1 >= 0.75, rubric marks >= 0.9, criteria F1 >= 0.9, OCR gate right on every case, every quote verified |
| `test_output_validates_against_the_exported_json_schema[g01..g10]` | each output passes the published `RequirementSet.schema.json` (what Member 3 reads) |
| `test_replay_is_deterministic` | the same input gives the same set twice |
| `test_model_failure_falls_back_to_rules_and_says_so` | a failing model -> keyword rules, confidence 0.6, an open question; tables still exact |
| `test_an_empty_answer_with_rule_hits_falls_back_to_rules` | an empty model answer where rules found items is treated as a miss |
| `test_no_model_at_all_still_produces_a_valid_set` | no LLM -> still a valid set |
| `test_mismatched_total_is_dropped_and_asked_about` | criteria 8 vs stated 10 -> `total_marks` empty + a question |
| `test_the_documents_modal_word_decides_priority` | "should" in the text wins over a model's "must" |
| `test_progress_and_cancellation` | progress only goes up and names the files; cancelling stops the run |

### `test_agent_api.py` — the agent (2.8), API (2.10), event (spec §7)
| Test | Proves |
|---|---|
| `test_plugin_shape` | the plug-in is valid, real (not a stub), priority above the stub, one slot |
| `test_agent_returns_requirement_set_and_document_model` | output artifacts and their order, `source_docs`, quotes, summary, evidence, progress |
| `test_agent_keeps_folders_and_names_typed_requests` | folders reach `SourceRef.folder`; a typed request is `request.txt` |
| `test_redelivered_task_does_no_model_work_twice` | **idempotent on redelivery**: same set, no second model call |
| `test_replayed_answers_name_the_recorded_model` | the document model records which model answered and the prompt version |
| `test_agent_without_documents_is_an_invalid_task` | no documents -> a non-retryable error |
| `test_lru_cache_is_bounded` | the in-memory cache cannot grow without limit |
| `test_requirements_ready_event` | `project.requirements_ready` carries the requirement-set ref |
| `test_upload_to_requirements_edit_and_ownership` | through the real app: upload -> extract -> plan with no manual step; GET requirements; PUT an edit = version 2; stale edit 409; invalid edit 422; document model; page PNG; another user gets 404 everywhere |

### `test_integration.py` — real infrastructure (DoD)
`test_multipart_upload_over_rabbitmq_and_postgres`: a three-part folder upload over RabbitMQ + Postgres reaches
the approval gate, every requirement keeps its folder, the marks add up to 50, and the event is published. Skips
with the reason when `make infra-up` is not running.

### Gateway (Member 1 code, made for Sprint 2): `tests/core/llm/`
- `test_vision.py` (6): images go only to the vision route; local-only projects, missing routes and failing keys
  raise `VisionUnavailable`; record/replay keys on the image hash and never stores the image or a key.
- `test_key_pool.py::test_gemini_never_gets_a_seed`: Gemini gets no `seed` (it answers 400) and reasoning is
  switched off; `gpt-oss` gets `reasoning_effort: low`; `think=True` turns that off.
- `test_key_pool.py::test_default_cloud_role_map_...`: every chat role (incl. `vision`) has a cloud route.
- `test_gateway.py::test_local_provider_gets_the_configured_context_window`: `HMAP_OLLAMA_NUM_CTX` reaches Ollama.

### Frontend: `frontend/src/features/doc_intel/logic.test.ts` (7)
Confidence labels; Confirm one / all (1.0 = checked by a person); grouping by folder; marks sum vs stated total;
quote highlighting (case and spacing, regex characters, span fallback); finding the source block; edit / remove /
add without changing the original.

## 4. Checked by hand (2026-10-12)
In the browser on the real stack (replay mode): the Requirements tab lists the set, "Source" shows the page image
with the sentence outlined, edit + "Save as version 2" works, "Confirm" marks an item as checked, developer mode
shows the model and OCR engine, and the phone width (375 px) has no sideways scrolling. A real IT 314 lab PDF
(not in the repo) was run through the cloud models: 31 requirements incl. every list item under a lead-in.

## 5. Known gaps
- No recorded vision (Gemini) answers yet: replay reads the scan and the photo with Tesseract, which is required
  for those two cases to score; re-record when Gemini's free daily quota resets.
- The UI is tested through its logic and by hand; there are no component (DOM) tests for the panel.
- The gold set is ours; real documents are only spot-checked (§4).
