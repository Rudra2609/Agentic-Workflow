"""Claim atomization and check-worthiness (Sprint 6 item 6.1).

A research claim often joins two facts ("X uses threads, while Y does not"); a compound claim is far more often half
right than wrong (FActScore), so each part is checked on its own and the claim gets the worst part's verdict.

Rules only (deterministic, no model call): split at sentence ends, semicolons and the contrast / consequence joints
", while", ", whereas", ", but", ", so", ", although". A relative clause (", which ...") or a plain "and" stays
with its claim: splitting those needs the subject repeated, and a wrong split creates claims nobody made. Parts that
are too short, questions or "no answer" notes are not check-worthy and are skipped (if nothing is left, the whole
claim is checked).

Atomic ids keep the claim id: ``C3`` → ``C3`` (one part) or ``C3.a``, ``C3.b``.
"""

import re
from dataclasses import dataclass

_SPLIT = re.compile(r"(?<=[a-z0-9)\]%])\.\s+(?=[A-Z])|;\s+|,\s+(?=(?:while|whereas|but|so|although|though)\s)",
                    re.IGNORECASE)
_LEAD = re.compile(r"^(?:while|whereas|but|so|although|though)\s+", re.IGNORECASE)
_NOT_WORTHY = re.compile(r"^(no sourced answer|not found|unknown|n/a)\b", re.IGNORECASE)
MIN_WORDS = 3
_FRAGMENT = re.compile(r"^(?:not|no|only|never|except|unless)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Atom:
    atom_id: str
    text: str
    check_worthy: bool


def _tidy(part: str) -> str:
    part = _LEAD.sub("", part.strip()).strip(" ,;")
    part = part.rstrip(".").strip()
    return part[:1].upper() + part[1:] if part else part


def check_worthy(text: str) -> bool:
    words = text.split()
    return len(words) >= MIN_WORDS and not text.rstrip().endswith("?") and not _NOT_WORTHY.match(text.strip())


def split_claim(text: str) -> list[str]:
    """The atomic parts of a claim (at least one: the claim itself)."""
    pieces: list[tuple[str, str]] = []          # (joint before the piece, piece) — the joint is kept for gluing
    last = 0
    for m in _SPLIT.finditer(text.strip()):
        pieces.append((text.strip()[last:m.start()], m.group(0)))
        last = m.end()
    pieces.append((text.strip()[last:], ""))
    merged: list[str] = []
    joint = ""
    for raw, sep in pieces:
        part = _tidy(raw)
        if not part:
            continue
        body = _LEAD.sub("", raw.strip())
        # too short, or a bare "not ..." / "only ...": a split in the wrong place, glued back to the part before
        if merged and (len(part.split()) < MIN_WORDS or _FRAGMENT.match(body)):
            merged[-1] = f"{merged[-1]}{joint}{raw.strip().rstrip('.')}"
        else:
            merged.append(part)
        joint = sep
    return merged or [text.strip()]


def atomize(claim_id: str, text: str) -> list[Atom]:
    parts = split_claim(text)
    if len(parts) == 1:
        return [Atom(claim_id, parts[0], check_worthy(parts[0]))]
    atoms = [Atom(f"{claim_id}.{chr(ord('a') + i)}", p, check_worthy(p)) for i, p in enumerate(parts[:26])]
    if not any(a.check_worthy for a in atoms):
        return [Atom(claim_id, text.strip(), True)]
    return atoms
