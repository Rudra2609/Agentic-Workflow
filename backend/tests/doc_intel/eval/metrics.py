"""Scoring a RequirementSet against a gold label file (spec item 2.13).

Matching is fuzzy, because a correct extraction may reword a sentence slightly: a predicted item matches a gold item
of the same kind and file when ``max(jaccard(texts), overlap(gold text, predicted quote))`` >= ``MATCH_THRESHOLD``.
Pairs are matched greedily by score, one to one. Criteria additionally need the same marks to count as "marks
correct".
"""

import difflib
from dataclasses import dataclass, field
from typing import Any

from hmap.agents.doc_intel.extract.quotes import jaccard, overlap, words
from hmap.agents.doc_intel.model import DocumentModel
from hmap.core.contracts.domain import RequirementSet

MATCH_THRESHOLD = 0.6


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else (1.0 if not self.fn else 0.0)

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def add(self, other: "PRF") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn


@dataclass
class DocScore:
    doc_id: str
    fields: dict[str, PRF] = field(default_factory=dict)
    priority_correct: int = 0
    priority_total: int = 0
    marks_correct: int = 0
    marks_total: int = 0
    total_marks_ok: bool = True
    quotes_verified: int = 0
    quotes_total: int = 0
    ocr_gate_ok: bool = True
    ocr_word_accuracy: float | None = None
    heading_recall: float = 1.0
    seconds: float = 0.0
    pages: int = 0
    misses: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)


def _score(pred_text: str, pred_quote: str | None, gold_text: str) -> float:
    return max(jaccard(pred_text, gold_text), overlap(gold_text, pred_quote or pred_text),
               overlap(gold_text, pred_text))


def match(preds: list[dict[str, Any]], golds: list[dict[str, Any]], gold_key: str = "text"
          ) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Greedy one-to-one matching. Returns (pairs, unmatched pred indexes, unmatched gold indexes)."""
    scored = []
    for i, p in enumerate(preds):
        for j, g in enumerate(golds):
            if p.get("file") and g.get("file") and p["file"] != g["file"]:
                continue
            s = _score(p["text"], p.get("quote"), g[gold_key])
            if s >= MATCH_THRESHOLD:
                scored.append((s, i, j))
    pairs: list[tuple[int, int]] = []
    used_p: set[int] = set()
    used_g: set[int] = set()
    for _, i, j in sorted(scored, reverse=True):
        if i not in used_p and j not in used_g:
            pairs.append((i, j))
            used_p.add(i)
            used_g.add(j)
    return pairs, [i for i in range(len(preds)) if i not in used_p], [j for j in range(len(golds)) if j not in used_g]


def word_accuracy(predicted: str, reference: str) -> float:
    a, b = words(predicted), words(reference)
    if not b:
        return 1.0
    return difflib.SequenceMatcher(a=b, b=a, autojunk=False).ratio()


def score_document(gold: dict[str, Any], rs: RequirementSet, model: DocumentModel, seconds: float) -> DocScore:
    names = {d.doc_id: d.name for d in model.documents}
    out = DocScore(doc_id=gold["id"], seconds=seconds, pages=sum(len(d.pages) or 1 for d in model.documents))

    def pred(items: list[Any], text_of: Any) -> list[dict[str, Any]]:
        res = []
        for it in items:
            ref = it.source_ref
            res.append({"text": text_of(it), "quote": ref.quote if ref else None,
                        "file": names.get(ref.doc_id) if ref else None, "obj": it})
        return res

    fields = {
        "requirements": (pred(rs.requirements, lambda r: r.text), gold["requirements"], "text"),
        "constraints": (pred(rs.constraints, lambda c: c.text), gold["constraints"], "text"),
        "deliverables": (pred(rs.deliverables, lambda d: d.name), gold["deliverables"], "text"),
        "evaluation_criteria": (pred(rs.evaluation_criteria, lambda e: e.criterion), gold["evaluation_criteria"],
                                "criterion"),
    }
    for name, (preds, golds, key) in fields.items():
        if name == "deliverables":  # a deliverable may be matched by its name or its sentence
            for g in golds:
                g["_match"] = g["name"] if len(g["text"]) < len(g["name"]) + 3 else g["text"]
            key = "_match"
        pairs, extra, missing = match(preds, golds, key)
        out.fields[name] = PRF(tp=len(pairs), fp=len(extra), fn=len(missing))
        out.misses += [f"{name}: {golds[j][key]}" for j in missing]
        out.extras += [f"{name}: {preds[i]['text']}" for i in extra]
        for i, j in pairs:
            obj, g = preds[i]["obj"], golds[j]
            if name == "requirements":
                out.priority_total += 1
                out.priority_correct += int(obj.priority == g["priority"])
            if name == "evaluation_criteria":
                out.marks_total += 1
                out.marks_correct += int(abs(obj.max_marks - g["max_marks"]) < 1e-6)
    gold_total = gold.get("total_marks")
    out.total_marks_ok = (rs.total_marks is None and gold_total is None) or (
        rs.total_marks is not None and gold_total is not None and abs(rs.total_marks - gold_total) < 1e-6)
    out.quotes_total = len(rs.requirements)
    out.quotes_verified = sum(1 for r in rs.requirements if r.source_ref.quote)

    ocr_pages = [p.ocr for d in model.documents for p in d.pages]
    if gold.get("needs_ocr"):
        out.ocr_gate_ok = bool(ocr_pages) and all(ocr_pages)
        text = "\n".join(d.text for d in model.documents)
        out.ocr_word_accuracy = word_accuracy(text, "\n".join(f["reference_text"] for f in gold["files"]))
    else:
        out.ocr_gate_ok = not any(ocr_pages)

    gold_heads = [s["title"] for f in gold["files"] for s in f["sections"]]
    got = [b.text for d in model.documents for b in d.blocks if b.type == "heading"]
    if gold_heads:
        found = sum(1 for h in gold_heads if any(jaccard(h, g) >= 0.8 or h.lower() == g.lower() for g in got))
        out.heading_recall = found / len(gold_heads)
    return out
