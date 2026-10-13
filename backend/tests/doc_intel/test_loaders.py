"""Loaders (spec item 2.1) and normalisation (item 2.2) on the gold documents: PDF, two-column PDF, DOCX, Markdown,
text, scanned PDF and photo. OCR uses a scripted vision model or is unavailable; no Tesseract, no network."""

import pytest

from hmap.agents.doc_intel.loaders import InputDocument, detect_kind, load_document
from hmap.agents.doc_intel.loaders.base import join_lines, strip_marker
from hmap.agents.doc_intel.loaders.text import parse_markdown
from hmap.agents.doc_intel.ocr import OcrEngine
from hmap.agents.doc_intel.structure import build_document
from hmap.core.llm import FakeLLM

from .conftest import gold_case, gold_doc

NO_OCR = OcrEngine(None, use_tesseract=False)


async def load(doc: InputDocument, ocr: OcrEngine = NO_OCR):  # type: ignore[no-untyped-def]
    return build_document(doc, await load_document(doc, ocr))


def headings(sd) -> list[tuple[int | None, str]]:  # type: ignore[no-untyped-def]
    return [(b.level, b.text) for b in sd.blocks if b.type == "heading"]


def test_detect_kind_by_content_not_just_name() -> None:
    assert detect_kind("x.txt", "", b"%PDF-1.7 ...") == "pdf"
    assert detect_kind("photo", "", b"\x89PNG\r\n\x1a\n") == "image"
    assert detect_kind("brief.docx", "", b"PK\x03\x04") == "docx"
    assert detect_kind("notes.md", "text/markdown", b"# hi") == "text"


def test_marker_and_line_helpers() -> None:
    assert strip_marker("1. Write tests") == ("Write tests", True)
    assert strip_marker("(cid:127) Use Python") == ("Use Python", True)
    assert strip_marker("10 clients connect") == ("10 clients connect", False)  # a number, not a list marker
    assert join_lines(["the require-", "ment is", "clear"]) == "the requirement is clear"


async def test_native_pdf_structure_and_sections(tcp_chat: InputDocument) -> None:
    sd = await load(tcp_chat)
    assert sd.kind == "pdf" and [p.ocr for p in sd.pages] == [False]  # native PDF: never OCR'd
    expected = [s["title"] for s in gold_case("g01_tcp_chat")["files"][0]["sections"]]
    assert [t for _, t in headings(sd)] == expected
    assert headings(sd)[0][0] == 1 and all(level == 2 for level, _ in headings(sd)[1:])
    items = [b for b in sd.blocks if b.type == "list_item"]
    assert items[0].text == "The server must accept at least 10 clients connected at the same time."
    assert items[0].section_path == ["IT 314 Assignment 2: Multi-client Chat Server", "1. Functional requirements"]
    assert all(b.bbox and 0 <= b.bbox[0] < b.bbox[2] <= 1 and 0 <= b.bbox[1] < b.bbox[3] <= 1 for b in items)
    assert [t.kind for t in sd.tables] == ["marks"]
    assert any(b.type == "note" and b.text.startswith("Late submissions") for b in sd.blocks)
    for b in sd.blocks:  # offsets index the document text exactly
        assert sd.text[b.char_start:b.char_end] == b.text


async def test_two_column_pdf_reads_columns_in_order_and_drops_furniture() -> None:
    sd = await load(gold_doc("g07_messy/weather_dashboard.pdf"))
    kinds = [b.type for b in sd.blocks]
    assert kinds[0] == "header" and "footer" in kinds and "note" in kinds
    assert headings(sd)[0] == (1, "Mini Project: Weather Data Dashboard")  # a title wrapped over two lines
    texts = [b.text for b in sd.blocks]
    first_req = next(i for i, t in enumerate(texts) if t.startswith("The dashboard must read the CSV files"))
    hand_in = texts.index("Hand-in")
    assert first_req < hand_in  # left column before right column


async def test_docx_styles_lists_and_tables() -> None:
    sd = await load(gold_doc("g02_lab_manual/lab4_unit_testing.docx"))
    assert sd.kind == "docx" and sd.pages == []
    assert headings(sd)[:3] == [(1, "Lab 4: Unit Testing with pytest"), (2, "Objectives"), (2, "Setup")]
    tasks = [b.text for b in sd.blocks if b.type == "list_item" and b.section_path[-1] == "Tasks"]
    assert len(tasks) == 6 and tasks[0].startswith("Write at least five unit tests")
    assert [t.kind for t in sd.tables] == ["marks"]
    assert not any(b.type == "heading" and b.text.startswith("Total") for b in sd.blocks)


async def test_docx_rubric_merged_cells_are_repeated() -> None:
    sd = await load(gold_doc("g06_project_brief/event_booking_brief.docx"))
    assert [t.kind for t in sd.tables] == ["deliverables"]


def test_markdown_parser() -> None:
    blocks = parse_markdown("# Title\n\nIntro line\ncontinues.\n\n- one\n  wrapped\n- two\n\n| A | Marks |\n|---|---|\n"
                            "| x | 5 |\n\n## Next\n1. first\n```\ncode fence\n```\n")
    assert [(b.type, b.text) for b in blocks] == [
        ("heading", "Title"), ("paragraph", "Intro line continues."), ("list_item", "one wrapped"),
        ("list_item", "two"), ("table", "| A | Marks |\n|---|---|\n| x | 5 |"), ("heading", "Next"),
        ("list_item", "first"), ("paragraph", "code fence")]
    assert blocks[4].rows == [["A", "Marks"], ["x", "5"]]


async def test_markdown_and_text_files() -> None:
    md = await load(gold_doc("g08_multipart/Part C/part_c.md", folder="Part C"))
    assert md.kind == "text" and headings(md) == [(1, "Part C: Testing")] and md.folder == "Part C"
    txt = await load(gold_doc("g09_request/request.txt"))
    assert [b.type for b in txt.blocks] == ["paragraph"] and txt.blocks[0].section_path == []


async def test_scanned_pdf_goes_to_ocr_and_vision_markdown_is_parsed() -> None:
    fake = FakeLLM().on_vision("# Assignment 3\n\n## Requirements\n1. The program must let a librarian add books.\n\n"
                               "| Criterion | Marks |\n|---|---|\n| Book management | 10 |\n")
    sd = await load(gold_doc("g04_scanned/library_assignment_scan.pdf"), OcrEngine(fake, use_tesseract=False))
    assert [(p.ocr, p.ocr_engine) for p in sd.pages] == [(True, "vision")] and len(fake.vision_calls) == 1
    assert headings(sd) == [(1, "Assignment 3"), (2, "Requirements")]
    assert sd.blocks[2].type == "list_item" and sd.blocks[2].ocr and sd.blocks[2].page == 1
    assert [t.kind for t in sd.tables] == ["marks"]


async def test_scan_without_any_ocr_is_reported_not_guessed() -> None:
    sd = await load(gold_doc("g04_scanned/library_assignment_scan.pdf"))
    assert sd.pages[0].ocr and sd.pages[0].ocr_engine is None and sd.blocks == []
    assert "no OCR is available" in sd.warnings[0]


async def test_photo_uses_vision_and_caches_it() -> None:
    from hmap.agents.doc_intel.cache import MemoryCache

    fake = FakeLLM().on_vision("- Write a function that returns the largest of three numbers.")
    cache = MemoryCache()
    engine = OcrEngine(fake, cache, use_tesseract=False)
    doc = gold_doc("g05_photo/quiz_handout_photo.png")
    first = await load(doc, engine)
    again = await load(doc, engine)
    assert first.kind == "image" and first.pages[0].ocr_engine == "vision"
    assert [b.text for b in again.blocks] == [b.text for b in first.blocks]
    assert len(fake.vision_calls) == 1  # the second read came from the cache


async def test_broken_files_become_warnings() -> None:
    bad_pdf = await load(InputDocument("d1", "x.pdf", b"%PDF-1.4 not really", "application/pdf"))
    bad_docx = await load(InputDocument("d2", "x.docx", b"PK\x03\x04 nope",
                                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
    assert bad_pdf.blocks == [] and "could not open the PDF" in bad_pdf.warnings[0]
    assert bad_docx.blocks == [] and "could not open the DOCX" in bad_docx.warnings[0]


@pytest.mark.skipif(not OcrEngine(None).use_tesseract, reason="Tesseract is not installed (brew install tesseract)")
async def test_tesseract_reads_the_photo() -> None:
    sd = await load(gold_doc("g05_photo/quiz_handout_photo.png"), OcrEngine(None))
    assert sd.pages[0].ocr_engine == "tesseract" and "largest of three numbers" in sd.text
