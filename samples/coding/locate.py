#!/usr/bin/env python3
"""BM25 file locator for the coding agent (Member 7, prepared ahead of Sprint 7 item 7.3). Plain Python 3.11.

Ranks the workspace's Python files for a task description, using identifiers (split on snake_case and camelCase),
docstrings, comments and the file name. Sprint 7 adds embeddings and an LLM re-rank on top. This is the lexical
half.

    python3 samples/coding/locate.py samples/coding/tasks/b2_broadcast_crash/starter "broadcast crashes ..."
"""

import math
import re
import sys
from collections import Counter
from pathlib import Path

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "be", "for", "on", "with", "when", "must",
        "should", "self", "def", "return", "import", "from", "none", "str", "int", "list", "dict", "true", "false",
        "if", "not", "as", "by", "at", "this", "that", "are", "was", "while", "one", "every", "bug", "report"}


def tokens(text: str) -> list[str]:
    words = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text):
        for part in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", word):
            part = part.lower()
            if len(part) > 1 and part not in STOP:
                words.append(part)
    return words


def rank(files: dict[str, str], query: str, k1: float = 1.2, b: float = 0.75) -> list[tuple[str, float]]:
    docs = {path: Counter(tokens(text) + tokens(Path(path).stem) * 3) for path, text in files.items()}
    n = len(docs)
    avg = sum(sum(c.values()) for c in docs.values()) / max(n, 1)
    df = Counter(t for c in docs.values() for t in c)
    scores = {}
    for path, counts in docs.items():
        length = sum(counts.values())
        score = 0.0
        for t in set(tokens(query)):
            if t in counts:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * counts[t] * (k1 + 1) / (counts[t] + k1 * (1 - b + b * length / avg))
        scores[path] = score
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def rank_folder(folder: Path, query: str) -> list[tuple[str, float]]:
    files = {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*.py"))}
    return rank(files, query)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    for path, score in rank_folder(Path(sys.argv[1]), " ".join(sys.argv[2:])):
        print(f"{score:6.2f}  {path}")
