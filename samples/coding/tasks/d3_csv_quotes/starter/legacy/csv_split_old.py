"""DEPRECATED: the first CSV splitter (no quotes support). Use io_utils.csv_reader."""


def old_split(line: str) -> list[str]:
    return line.split(",")
