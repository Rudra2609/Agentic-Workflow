# Research — Member 2: document intelligence

## 1. Problem
Students and teams upload assignment briefs, lab sheets, rubrics and scanned handouts in many formats (native PDF,
DOCX, scans, phone photos, plain text, folders with several parts). The planner (Member 3) needs one clean,
**traceable** list: requirements, constraints, deliverables and marking criteria, each pointing to the exact sentence
it came from. It is hard because layouts vary (two columns, headers, footnotes, merged table cells), scans need OCR,
local 9B models invent or merge items, and marks must add up exactly.

## 2. Concepts
- **Native vs scanned PDF.** A native PDF has a text layer with character positions; a scanned page is an image
  that needs OCR. Per-page gating (text density) avoids OCR on pages that already have text [1, 6].
- **Layout analysis.** Words -> lines -> blocks using positions, font size and weight; column gutters are wide
  gaps between words on the same line; running headers/footers sit in the page margins [1].
- **Table extraction.** Ruling lines and text alignment give cells; merged cells come back empty (pdfplumber) or
  repeated (python-docx) and must be filled from the row above [1, 3].
- **Requirement language.** Modal verbs mark obligation strength: must/shall (mandatory), should (recommended),
  may/could (optional), like RFC 2119 [9] and the IEEE requirements-language guidance [10].
- **Schema-constrained extraction + verification.** Ask the model for JSON matching a schema, then verify every
  claim against the source by string match ("quote required"), the cheapest guard against invented items [11].
- **Map-reduce over a long document.** Small-context local models get section-sized chunks; results are merged and
  deduplicated afterwards [12].

## 3. Approaches compared

### 3.1 PDF text (measured on the 4 native gold PDFs, `samples/doc_intel/gold`, 5 runs each)
| Library | Word accuracy vs reference | ms / document | Tables | Licence | Fit |
|---|---|---|---|---|---|
| pdfplumber (plain `extract_text`) | 0.860 | 172 | yes (`find_tables`) | MIT | good: positions, fonts, tables |
| pypdfium2 (`get_text_range`) | 0.870 | 59 | no | Apache/BSD | fastest; used to **render** pages for OCR |
| PyMuPDF | 0.870 | 456 (incl. first import) | partial | **AGPL** | strong, but AGPL in a public repo |
| **our loader** (pdfplumber words + layout rules) | **0.883** | 136 | yes | MIT | chosen |

Plain text is nearly the same in every library; the differences are layout: headers/footers, columns, bullets that
pdfminer writes as `(cid:127)`, tables and marks. The rubric document scores 0.60 everywhere because its reference
text omits the rubric-level descriptions (same for all rows). Docling and Unstructured (ML layout models) were read
about, not run: they need large model downloads and gain little on course documents [7, 8].

### 3.2 DOCX
| Approach | Strengths | Weaknesses | Decision |
|---|---|---|---|
| python-docx [3] | styles give headings and lists exactly; tables in body order | no page numbers | **chosen** |
| LibreOffice -> PDF -> PDF loader | page numbers and images | 300+ MB install; the demo laptop's install is broken | rejected |

### 3.3 OCR (scanned pages and photos)
| Engine | Strengths | Weaknesses | Decision |
|---|---|---|---|
| Gemini vision via the team key pool | reads skew, noise and photos; returns Markdown, so headings/lists/tables survive; word accuracy **0.997** on our scan + photo | cloud: quota, privacy | **first choice** when the project allows the cloud |
| Tesseract 5 [4] (+ OCRmyPDF [5]) | local, free, every OS | plain text only, weaker on photos | **fallback** (local-only projects, no keys) |
| PaddleOCR [6] | accurate | heavy install (PaddlePaddle) on 16 GB | rejected |
| Apple Vision (`ocrmac`) | excellent, no install | macOS only (teammates use Windows/Linux) | rejected |
Measured on our scan and photo: Gemini vision 0.997 word accuracy; Tesseract 5.5 0.974 after three steps that
each helped: erasing long ruled lines (tables), single-column layout (`--psm 4`), and deskewing only tilts of 2
degrees or more (re-rotating a 1.2-degree scan blurred it: 0.96 vs 0.98).

### 3.4 Extraction
| Approach | Requirements F1 (gold set) | Notes |
|---|---|---|
| Rules only (modal verbs, section names, imperatives) | 0.84 | precise (P 1.00) but misses items without modal verbs; cannot read scans |
| LLM per chunk, prompt v1 | 0.92 | confused requirement vs constraint on borderline sentences |
| **Hybrid: rules as hints + LLM (prompt v2) + quote check + table rules** | **0.95** | chosen; marks read from tables by code, never by the model |
Numbers: `docs/members/2/eval.md`.

## 4. Chosen approach and why
Hybrid, deterministic where possible: pdfplumber/python-docx/Markdown loaders with layout rules; OCR only for pages
without a text layer (vision model first, Tesseract second); marks and deliverables tables read by code; the
`reasoner` role extracts per section-aligned chunk (about 3K tokens, which fits Gemini, Groq's 8K tokens/min free
limit and the local `qwen3.5:9b`); every item must quote its source and the quote is checked by string match; marks
must add up or the total is withheld and a question is asked. Rejected: one whole-document prompt (breaks on the local
model and on Groq), ML layout models (size), PyMuPDF (AGPL), LibreOffice conversion (install).

## 5. Risks and open questions
- Tesseract still loses a row of a ruled table now and then; vision OCR uses cloud quota.
- The gold set is authored by us and was also used during development (prompt v2), so the scores are optimistic;
  real course documents may be messier (Sprint-11 or a later member can add real ones).
- Requirement vs constraint is sometimes a judgment call (e.g. "Use pytest.mark.parametrize").

## 6. Sources
1. pdfplumber — https://github.com/jsvine/pdfplumber
2. pypdfium2 — https://github.com/pypdfium2-team/pypdfium2
3. python-docx — https://python-docx.readthedocs.io/
4. Tesseract OCR — https://github.com/tesseract-ocr/tesseract
5. OCRmyPDF — https://ocrmypdf.readthedocs.io/
6. PaddleOCR — https://github.com/PaddlePaddle/PaddleOCR
7. Docling — https://github.com/docling-project/docling
8. Unstructured — https://github.com/Unstructured-IO/unstructured
9. RFC 2119, key words for requirement levels — https://www.rfc-editor.org/rfc/rfc2119
10. ISO/IEC/IEEE 29148:2018, requirements engineering (requirement language)
11. Gemini API, OpenAI compatibility and structured output — https://ai.google.dev/gemini-api/docs/openai
12. LangChain docs, map-reduce summarisation pattern — https://python.langchain.com/docs/how_to/summarize_map_reduce/
13. PyMuPDF licensing (AGPL / commercial) — https://pymupdf.readthedocs.io/en/latest/about.html
