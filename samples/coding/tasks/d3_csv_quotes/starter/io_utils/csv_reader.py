"""Read CSV text into rows of fields."""


def split_line(line: str) -> list[str]:
    """Fields of one CSV line."""
    return [field.strip() for field in line.rstrip("\n").split(",")]


def read_rows(text: str) -> list[list[str]]:
    return [split_line(line) for line in text.splitlines() if line.strip()]
