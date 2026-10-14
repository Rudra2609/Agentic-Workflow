"""Quote-must-match (Sprint 5 item 5.7, plan D9): a quote counts only if it is a verbatim substring of the page's
cleaned text. "Verbatim" ignores only typography — runs of whitespace, curly vs straight quotes, the different
dashes, the ellipsis character — never words, case or punctuation. The match returns the span in the ORIGINAL text,
so evidence points at exactly what the page says (Member 6 re-checks it against ``content_sha256``)."""

import re

_SINGLE = (0x2018, 0x2019, 0x201A, 0x201B, 0x2032)
_DOUBLE = (0x201C, 0x201D, 0x201E, 0x2033)
_DASHES = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)
_SPACES = (0x00A0, 0x2009, 0x202F)
_TRANS = str.maketrans({**{chr(c): "'" for c in _SINGLE}, **{chr(c): '"' for c in _DOUBLE},
                        **{chr(c): "-" for c in _DASHES}, **{chr(c): " " for c in _SPACES}})
_WS = re.compile(r"\s+")
MIN_QUOTE_CHARS = 20
MAX_QUOTE_CHARS = 600


def _normalise_char(c: str) -> str:
    if c == "…":
        return "..."
    return c.translate(_TRANS)


def normalise(text: str) -> tuple[str, list[int]]:
    """Normalised text + for each of its characters the index of the original character it came from."""
    out: list[str] = []
    origin: list[int] = []
    space = False
    for i, c in enumerate(text):
        n = _normalise_char(c)
        if n.isspace():
            if not space and out:
                out.append(" ")
                origin.append(i)
            space = True
            continue
        space = False
        for ch in n:
            out.append(ch)
            origin.append(i)
    while out and out[-1] == " ":
        out.pop()
        origin.pop()
    return "".join(out), origin


def clean_quote(quote: str) -> str:
    q, _ = normalise(quote.strip().strip('"').strip("'").strip())
    return q.strip(" .;:,")


def locate(quote: str, text: str) -> tuple[int, int] | None:
    """(start, end) of ``quote`` in ``text`` (original offsets), or ``None`` when it is not there verbatim. Too
    short (< 20 characters) or too long (> 600) quotes are refused: a short one proves nothing, a long one is a
    copy of the page, not evidence."""
    q = clean_quote(quote)
    if not (MIN_QUOTE_CHARS <= len(q) <= MAX_QUOTE_CHARS):
        return None
    norm, origin = normalise(text)
    at = norm.find(q)
    if at < 0:
        return None
    start = origin[at]
    end = origin[at + len(q) - 1] + 1
    return start, end


def verify(quote: str, text: str) -> str | None:
    """The verbatim quote as it appears in ``text`` (original characters), or ``None``."""
    span = locate(quote, text)
    return text[span[0]:span[1]] if span else None


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}
