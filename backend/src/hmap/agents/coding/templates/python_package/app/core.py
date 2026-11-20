"""Core logic of the package."""


def normalise(text: str) -> str:
    """Example function: collapse whitespace and lower-case."""
    return " ".join(text.split()).lower()
