"""Small text signals shared by the layers: content words, numbers, years, negation. Deterministic."""

import re
from urllib.parse import urlsplit

_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_NUMBER = re.compile(r"(?<![a-z])(\d+(?:[.,]\d+)?)(?:\s?(%|percent|ms|s|kb|mb|gb|x))?(?![a-z])", re.IGNORECASE)
_EMBEDDED = re.compile(r"[a-z]+-?(\d+)", re.IGNORECASE)        # SHA-256, HS256, UTF-8
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
NEGATIONS = frozenset({"not", "no", "never", "without", "cannot", "can't", "doesn't", "don't", "isn't", "aren't",
                       "wasn't", "won't", "none", "neither", "nor", "lacks", "unable", "impossible"})
_TYPO = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
                       "\u2212": "-", "\u2018": "'", "\u2019": "'", "\u00a0": " ", "\u202f": " ", "\u2009": " "})
_STOP = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "was", "were", "be", "been",
    "by", "as", "at", "it", "its", "this", "that", "these", "those", "from", "which", "who", "when", "what", "how",
    "can", "could", "may", "might", "will", "would", "should", "than", "then", "into", "also", "more", "most", "such",
    "their", "there", "they", "them", "has", "have", "had", "do", "does", "so", "if", "while", "but", "via", "per",
    "use", "uses", "used", "using", "one", "many", "much", "very", "only", "other", "each", "all", "any", "both",
})


def normalise(text: str) -> str:
    return text.translate(_TYPO).lower()


def content_words(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(normalise(text)):
        if w in _STOP or len(w) < 3:
            continue
        out.append(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def overlap(claim: str, text: str) -> float:
    """Share of the claim's distinct content words that occur in ``text`` (0..1)."""
    want = set(content_words(claim))
    if not want:
        return 0.0
    have = set(content_words(text))
    return len(want & have) / len(want)


def numbers(text: str) -> set[str]:
    t = normalise(text)
    out = {m.group(1).replace(",", "") for m in _NUMBER.finditer(t)}
    out |= {m.group(1) for m in _EMBEDDED.finditer(t)}
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in out}


def years(text: str) -> set[str]:
    return set(_YEAR.findall(text))


def negated(text: str) -> bool:
    words = set(_WORD.findall(normalise(text)))
    return bool(words & NEGATIONS) or "n't" in normalise(text)


def missing_numbers(claim: str, evidence_text: str) -> set[str]:
    """Numbers the claim states that the evidence never mentions (a changed figure is the commonest error)."""
    return numbers(claim) - numbers(evidence_text)


def host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def site(url: str) -> str:
    """The registrable-ish domain (``en.wikipedia.org`` → ``wikipedia.org``) for domain-diversity counting."""
    parts = host(url).split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host(url)
