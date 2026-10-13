"""Tables (spec item 2.3): marks / rubric tables -> evaluation criteria, deliverables tables -> deliverables.

Rules, not the LLM: marks are numbers and must add up, so they are read straight from the cells. Merged cells come
back empty (PDF) or repeated (DOCX); empty cells in the leftmost column are filled from the row above.
"""

import re
from dataclasses import dataclass, field

from hmap.agents.doc_intel.model import TableKind

MARKS_HEADER_RE = re.compile(r"\b(marks?|points?|pts|score|weight(?:ing)?|max(?:imum)?)\b", re.IGNORECASE)
CRITERION_HEADER_RE = re.compile(r"\b(criteri(?:on|a)|component|aspect|item|task|part|question|area)\b",
                                 re.IGNORECASE)
SECTION_HEADER_RE = re.compile(r"\b(section|category|group|stage)\b", re.IGNORECASE)
DELIVERABLE_HEADER_RE = re.compile(r"\b(deliverables?|artefacts?|artifacts?|submission)\b", re.IGNORECASE)
FORMAT_HEADER_RE = re.compile(r"\b(format|type|file)\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"^\s*(\d{1,4}(?:\.\d+)?)\s*(?:marks?|points?|pts|%)?\s*$", re.IGNORECASE)
LEVEL_MARKS_RE = re.compile(r"\((\d{1,3}(?:\.\d+)?)(?:\s*(?:marks?|points?|pts))?\)\s*$", re.IGNORECASE)
LEVEL_RANGE_RE = re.compile(r"\((\d{1,3})\s*[-\u2013]\s*(\d{1,3})\)\s*$")
TOTAL_ROW_RE = re.compile(r"^\s*(grand\s+)?total\b", re.IGNORECASE)
TOTAL_TEXT_RES = [
    re.compile(r"\btotal\s*(?:of|:|-|=)?\s*(\d{1,4}(?:\.\d+)?)\s*(?:marks|points)\b", re.IGNORECASE),
    re.compile(r"\bworth\s+(\d{1,4}(?:\.\d+)?)\s+(?:marks|points)\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s+(?:marks|points)\s+in\s+total\b", re.IGNORECASE),
    re.compile(r"\bout\s+of\s+(\d{1,4}(?:\.\d+)?)\s*(?:marks|points)?\b", re.IGNORECASE),
]


@dataclass
class CriterionRow:
    criterion: str
    max_marks: float
    levels: list[tuple[str, str, float | None]] = field(default_factory=list)  # (label, description, marks)
    group: str = ""
    row_index: int = 0


@dataclass
class TableReading:
    kind: TableKind
    criteria: list[CriterionRow] = field(default_factory=list)
    deliverables: list[tuple[str, str]] = field(default_factory=list)  # (name, format)
    total: float | None = None


def _num(text: str) -> float | None:
    m = NUMBER_RE.match(text or "")
    return float(m.group(1)) if m else None


def fill_down(rows: list[list[str]], columns: int = 1) -> list[list[str]]:
    """Merged cells: an empty cell in the first ``columns`` columns takes the value from the row above."""
    out: list[list[str]] = []
    for r, row in enumerate(rows):
        row = list(row)
        if r > 1:  # never fill from the header row
            for c in range(min(columns, len(row))):
                if not row[c].strip() and c < len(out[-1]):
                    row[c] = out[-1][c]
        out.append(row)
    return out


def read_table(rows: list[list[str]]) -> TableReading:
    if len(rows) < 2:
        return TableReading("other")
    header = [c.strip() for c in rows[0]]
    width = max(len(r) for r in rows)
    body = [r + [""] * (width - len(r)) for r in rows[1:]]
    if any(DELIVERABLE_HEADER_RE.search(h) for h in header[:1]):
        fmt_col = next((i for i, h in enumerate(header) if i > 0 and FORMAT_HEADER_RE.search(h)), None)
        items = [(r[0].strip(), r[fmt_col].strip() if fmt_col is not None else "") for r in body if r[0].strip()]
        return TableReading("deliverables", deliverables=items)

    marks_col = next((i for i, h in enumerate(header)
                      if MARKS_HEADER_RE.search(h) and not CRITERION_HEADER_RE.search(h)), None)
    has_header = marks_col is not None
    if marks_col is None:  # no header: a column whose cells are (almost) all numbers
        all_rows = [r + [""] * (width - len(r)) for r in rows]
        for c in range(1, width):
            nums = [_num(r[c]) for r in all_rows]
            if sum(n is not None for n in nums) >= max(2, int(0.8 * len(all_rows))):
                marks_col = c
                body = all_rows
                header = [""] * width
                break
    if marks_col is None:
        return TableReading("other")
    crit_col = next((i for i, h in enumerate(header) if i != marks_col and CRITERION_HEADER_RE.search(h)), None)
    if crit_col is None:
        crit_col = marks_col - 1 if marks_col > 0 else 0
    group_col = next((i for i in range(crit_col) if SECTION_HEADER_RE.search(header[i]) or not has_header), None)
    level_cols = [i for i in range(width) if i not in (marks_col, crit_col, group_col) and header[i]
                  and i > crit_col]
    body = fill_down([header, *body], columns=crit_col)[1:] if crit_col > 0 else body

    reading = TableReading("rubric" if level_cols else "marks")
    for idx, row in enumerate(body, start=1):
        name = row[crit_col].strip()
        marks = _num(row[marks_col])
        if not name and marks is None:
            continue
        if TOTAL_ROW_RE.match(name) or (group_col is not None and TOTAL_ROW_RE.match(row[group_col])):
            reading.total = marks
            continue
        if marks is None or not name:
            continue
        levels: list[tuple[str, str, float | None]] = []
        for c in level_cols:
            cell = row[c].strip()
            if not cell:
                continue
            lm = LEVEL_MARKS_RE.search(cell)
            rng = LEVEL_RANGE_RE.search(cell)
            level_marks = float(lm.group(1)) if lm else (float(rng.group(2)) if rng else None)
            desc = (cell[:lm.start()] if lm else cell[:rng.start()] if rng else cell).strip()
            levels.append((header[c], desc, level_marks))
        reading.criteria.append(CriterionRow(name, marks, levels, row[group_col].strip() if group_col is not None
                                             else "", idx))
    return reading if reading.criteria else TableReading("other")


def stated_total(text: str) -> float | None:
    """The total marks a document states in prose ("Total: 100 marks", "worth 50 marks in total")."""
    for pattern in TOTAL_TEXT_RES:
        m = pattern.search(text)
        if m:
            return float(m.group(1))
    return None
