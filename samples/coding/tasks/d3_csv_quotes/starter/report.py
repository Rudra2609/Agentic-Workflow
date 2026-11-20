"""Summary of a CSV file: number of rows and columns."""

from io_utils.csv_reader import read_rows


def shape(text: str) -> tuple[int, int]:
    rows = read_rows(text)
    return len(rows), max((len(r) for r in rows), default=0)
