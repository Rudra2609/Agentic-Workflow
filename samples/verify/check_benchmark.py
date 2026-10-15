#!/usr/bin/env python3
"""Validate the seeded-hallucination benchmark (plain Python 3.11, no project imports; exits 1 on any problem).

Checks: required fields and allowed values; >= 60 seeded items with >= 15 of each seeded kind; every page file
exists and its text hashes to ``content_sha256``; quotes expected to be verbatim are in their page (typography
ignored) and planted fake quotes are not; every evidence hash matches its page; contradiction items carry a
synthetic counter source, and no other item does; ids are unique.

    python3 samples/verify/check_benchmark.py
"""

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KINDS = {"clean", "fake_quote", "wrong_number", "unsupported_claim", "contradiction", "natural"}
SEEDED = {"fake_quote", "wrong_number", "unsupported_claim", "contradiction"}
VERDICTS = {"VERIFIED", "UNSUPPORTED", "CONFLICTING", "NEEDS_MORE_RESEARCH"}
EXPECTED_VERDICT = {"clean": "VERIFIED", "fake_quote": "UNSUPPORTED", "wrong_number": "UNSUPPORTED",
                    "unsupported_claim": "UNSUPPORTED", "contradiction": "CONFLICTING", "natural": "UNSUPPORTED"}


def norm(text: str) -> str:
    table = str.maketrans({chr(c): "'" for c in (0x2018, 0x2019)} | {chr(c): '"' for c in (0x201C, 0x201D)}
                          | {chr(c): "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014)} | {chr(0x00A0): " "})
    return " ".join(text.translate(table).split())


def main() -> int:
    problems: list[str] = []
    items = [json.loads(line) for line in (HERE / "benchmark.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    pages: dict[str, dict] = {}
    for f in sorted((HERE / "pages").glob("*.json")):
        page = json.loads(f.read_text(encoding="utf-8"))
        if hashlib.sha256(page["text"].encode("utf-8")).hexdigest() != page["content_sha256"]:
            problems.append(f"{f.name}: text does not hash to content_sha256")
        if not page.get("license"):
            problems.append(f"{f.name}: no licence")
        pages[f"pages/{f.name}"] = page

    ids = [i["id"] for i in items]
    if len(ids) != len(set(ids)):
        problems.append("duplicate ids")
    counts: dict[str, int] = {}
    for i in items:
        where = i["id"]
        kind = i.get("kind")
        counts[kind] = counts.get(kind, 0) + 1
        if kind not in KINDS:
            problems.append(f"{where}: unknown kind {kind}")
            continue
        exp = i.get("expected", {})
        if exp.get("verdict") not in VERDICTS or exp.get("verdict") != EXPECTED_VERDICT[kind]:
            problems.append(f"{where}: verdict {exp.get('verdict')} for {kind}")
        if not i.get("claim") or not i.get("evidence"):
            problems.append(f"{where}: claim or evidence missing")
        for e in [*i.get("evidence", []), *i.get("counter_evidence", [])]:
            page = pages.get(e.get("page", ""))
            if page is None:
                problems.append(f"{where}: page {e.get('page')} missing")
                continue
            if page["content_sha256"] != e["content_sha256"]:
                problems.append(f"{where}: evidence {e['id']} hash does not match its page")
            found = norm(e["quote"]).rstrip(" .") in norm(page["text"])
            planted = kind == "fake_quote" and i.get("changed", {}).get("field") == f"evidence {e['id']} quote"
            if planted and found:
                problems.append(f"{where}: planted fake quote {e['id']} IS in the page")
            if not planted and not found:
                problems.append(f"{where}: quote {e['id']} is not in its page")
        has_counter = bool(i.get("counter_evidence"))
        if (kind == "contradiction") != has_counter:
            problems.append(f"{where}: counter evidence only for contradictions")
        for e in i.get("counter_evidence", []):
            if not pages.get(e["page"], {}).get("synthetic"):
                problems.append(f"{where}: counter source must be a synthetic page")
        if kind == "fake_quote" and exp.get("l1_quotes_verbatim") is not False:
            problems.append(f"{where}: fake quote must expect l1_quotes_verbatim = false")
    seeded = sum(counts.get(k, 0) for k in SEEDED)
    if seeded < 60 or any(counts.get(k, 0) < 15 for k in SEEDED):
        problems.append(f"need >= 60 seeded items and >= 15 per kind, got {counts}")
    for p in problems:
        print("PROBLEM:", p)
    print(f"{len(items)} items, {seeded} seeded, {counts}; pages {len(pages)}: "
          f"{'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
