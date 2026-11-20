"""Smart quotes -> plain quotes in text fields."""


def plain_quotes(text: str) -> str:
    return text.replace("\u201c", '"').replace("\u201d", '"')
