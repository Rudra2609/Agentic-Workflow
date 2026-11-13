"""Context budgeter (Sprint 7 item 7.8, plan D10): every prompt fits ``HMAP_CODING_PROMPT_TOKENS``.

The local ``coder`` sees an 8k window (``ollama_num_ctx``), so the default prompt budget is 5,500 tokens plus a
1,024-token answer. The same budget is used for cloud routes so local and cloud prompts are identical (replay).
Tokens are estimated as characters / 3 (conservative for code). Parts have a priority; required parts (the task,
the latest failure) are always kept, the others are added in priority order and the last one that does not fit is
cut in the middle. :func:`fit` never returns more than the budget.
"""

import math
from dataclasses import dataclass

CHARS_PER_TOKEN = 3
CUT = "\n…[cut to fit the context budget]…\n"


def tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass
class Part:
    name: str
    text: str
    priority: int = 50           # lower = more important
    required: bool = False
    min_tokens: int = 60         # don't keep a cut-down part smaller than this


def cut_middle(text: str, max_tokens: int) -> str:
    limit = max_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(CUT))
    return text[: keep * 2 // 3] + CUT + text[len(text) - keep // 3:] if keep else ""


def fit(parts: list[Part], budget: int, *, separator: str = "\n\n") -> tuple[list[Part], list[str]]:
    """Choose and cut parts so ``tokens(separator.join(texts)) <= budget``. Returns (kept parts in their original
    order, names of dropped or cut parts)."""
    sep = tokens(separator) + 1
    order = sorted(range(len(parts)), key=lambda i: (not parts[i].required, parts[i].priority, i))
    kept: dict[int, Part] = {}
    changed: list[str] = []
    left = budget
    for i in order:
        p = parts[i]
        need = tokens(p.text) + sep
        if need <= left:
            kept[i] = p
            left -= need
            continue
        room = left - sep - 1
        if room >= (1 if p.required else p.min_tokens):
            kept[i] = Part(p.name, cut_middle(p.text, room), p.priority, p.required, p.min_tokens)
            left -= tokens(kept[i].text) + sep
            changed.append(f"{p.name} (cut)")
        else:
            changed.append(f"{p.name} (dropped)")
    out = [kept[i] for i in sorted(kept)]
    while out and tokens(separator.join(p.text for p in out)) > budget:   # rounding guard
        last = max(range(len(out)), key=lambda k: (not out[k].required, out[k].priority))
        p = out[last]
        out[last] = Part(p.name, cut_middle(p.text, max(0, tokens(p.text) - 20)), p.priority, p.required)
        if not out[last].text:
            out.pop(last)
    return out, changed


Span = tuple[int, int]


def window(text: str, ranges: list[Span], *, pad: int = 30, whole_max_lines: int = 150) -> tuple[str, int, int]:
    """A slice of ``text`` covering ``ranges`` (1-based line spans) plus ``pad`` lines around; the whole file when
    it is short. Returns (slice, first line, last line)."""
    lines = text.split("\n")
    n = len(lines)
    if n <= whole_max_lines or not ranges:
        return text, 1, n
    a = max(1, min(r[0] for r in ranges) - pad)
    b = min(n, max(r[1] for r in ranges) + pad)
    return "\n".join(lines[a - 1:b]), a, b
