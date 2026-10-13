"""Tables -> criteria (item 2.3), heading levels (2.2) and chunking (2.4)."""

from hmap.agents.doc_intel.chunking import Chunk, estimate_tokens, make_chunks
from hmap.agents.doc_intel.loaders import load_document
from hmap.agents.doc_intel.loaders.base import Loaded, RawBlock
from hmap.agents.doc_intel.ocr import OcrEngine
from hmap.agents.doc_intel.structure import build_document
from hmap.agents.doc_intel.tables import fill_down, read_table, stated_total

from .conftest import gold_doc

RUBRIC = [["Section", "Criterion", "Marks", "Excellent", "Weak"],
          ["Analysis", "Use cases", "6", "All actors (6)", "Missing (1)"],
          ["", "Testable requirements", "8", "Every one (8)", "Few (2)"],
          ["Design", "Class diagram", "10", "Matches (10)", "No (2-3)"],
          ["Total", "", "24", "", ""]]


def test_rubric_with_merged_section_cells_and_level_marks() -> None:
    r = read_table(RUBRIC)
    assert r.kind == "rubric" and r.total == 24
    assert [(c.criterion, c.max_marks, c.group) for c in r.criteria] == [
        ("Use cases", 6, "Analysis"), ("Testable requirements", 8, "Analysis"), ("Class diagram", 10, "Design")]
    assert r.criteria[0].levels == [("Excellent", "All actors", 6.0), ("Weak", "Missing", 1.0)]
    assert r.criteria[2].levels[1] == ("Weak", "No", 3.0)  # a range: its top


def test_marks_deliverables_headerless_and_other_tables() -> None:
    marks = read_table([["Criterion", "Marks"], ["Broadcasting", "30"], ["Report", "10 marks"]])
    assert marks.kind == "marks" and [(c.criterion, c.max_marks) for c in marks.criteria] == [
        ("Broadcasting", 30), ("Report", 10)]
    deliv = read_table([["Deliverable", "Format", "Due"], ["Spec", "PDF", "Week 8"], ["Code", "Repository", "W12"]])
    assert deliv.kind == "deliverables" and deliv.deliverables == [("Spec", "PDF"), ("Code", "Repository")]
    headerless = read_table([["Book management", "10"], ["Saving data", "5"], ["User guide", "5"]])
    assert headerless.kind == "marks" and len(headerless.criteria) == 3
    assert read_table([["Name", "Email"], ["Ada", "ada@example.test"]]).kind == "other"
    assert read_table([["only header"]]).kind == "other"
    assert fill_down([["h", "x"], ["a", "1"], ["", "2"]]) == [["h", "x"], ["a", "1"], ["a", "2"]]


def test_stated_totals() -> None:
    assert stated_total("Total: 100 marks") == 100
    assert stated_total("The project is worth 50 marks in total.") == 50
    assert stated_total("marked out of 30") == 30
    assert stated_total("Late work loses 10 % per day.") is None


def test_heading_levels_from_size_and_numbering() -> None:
    blocks = [RawBlock("heading", "Big", size=16), RawBlock("heading", "1 Medium", size=13),
              RawBlock("heading", "1.2 Numbered sub", size=13), RawBlock("paragraph", "text"),
              RawBlock("heading", "Another", size=13)]
    from hmap.agents.doc_intel.loaders import InputDocument

    sd = build_document(InputDocument("d", "x.pdf", b""), Loaded("pdf", blocks))
    assert [(b.level, b.text) for b in sd.blocks if b.type == "heading"] == [
        (1, "Big"), (2, "1 Medium"), (3, "1.2 Numbered sub"), (2, "Another")]
    assert sd.blocks[3].section_path == ["Big", "1 Medium", "1.2 Numbered sub"]


async def test_chunks_skip_tables_and_furniture_and_respect_the_budget() -> None:
    doc = gold_doc("g07_messy/weather_dashboard.pdf")
    sd = build_document(doc, await load_document(doc, OcrEngine(None, use_tesseract=False)))
    [chunk] = make_chunks([sd])
    text = chunk.text
    assert text.startswith("Document: weather_dashboard.pdf") and "# Mini Project: Weather Data Dashboard" in text
    assert "Page 1" not in text and "UTC timestamps" not in text and "| Criterion |" not in text
    small = make_chunks([sd], budget=60)  # tiny budget: split, but at section boundaries where possible
    assert len(small) > 1 and all(isinstance(c, Chunk) for c in small)
    assert all(c.tokens <= 60 or len([b for b in c.blocks if b.type != "heading"]) == 1 for c in small)
    assert [c.index for c in small] == list(range(len(small)))
    assert estimate_tokens("x" * 400) == 100


async def test_chunks_never_span_documents() -> None:
    a, b = gold_doc("g08_multipart/Part A/part_a.pdf", "d1", "Part A"), gold_doc("g08_multipart/Part C/part_c.md",
                                                                                   "d2", "Part C")
    ocr = OcrEngine(None, use_tesseract=False)
    docs = [build_document(d, await load_document(d, ocr)) for d in (a, b)]
    chunks = make_chunks(docs)
    assert [c.doc_index for c in chunks] == [0, 1]
    assert "(folder: Part C)" in chunks[1].text
