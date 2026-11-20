"""Read TSV lines (fields split on tabs)."""


def split_tsv_line(line: str) -> list[str]:
    return line.rstrip("\n").split("\t")
