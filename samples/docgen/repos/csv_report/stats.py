"""Column statistics for CSV files."""

import csv
import statistics
from pathlib import Path


def load(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def numeric_columns(rows: list[dict[str, str]]) -> list[str]:
    def is_number(value: str) -> bool:
        try:
            float(value)
        except ValueError:
            return False
        return True

    return [c for c in rows[0] if all(is_number(r[c]) for r in rows)] if rows else []


def summarize(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    result = {}
    for column in numeric_columns(rows):
        values = [float(r[column]) for r in rows]
        result[column] = {"min": min(values), "max": max(values), "mean": statistics.fmean(values),
                          "median": statistics.median(values)}
    return result
