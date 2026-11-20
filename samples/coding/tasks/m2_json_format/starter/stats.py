"""Column statistics for CSV files."""

import csv
from pathlib import Path


def load(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def summarize(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    """min / max / mean / median of every numeric column."""
    out = {}
    for column in rows[0] if rows else []:
        try:
            values = [float(r[column]) for r in rows]
        except ValueError:
            continue
        out[column] = {"min": min(values), "max": max(values), "mean": sum(values) / len(values),
                       "median": median(values)}
    return out
