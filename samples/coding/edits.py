#!/usr/bin/env python3
"""Search/replace edit applicator for the coding agent (Member 7, prepared ahead of Sprint 7 item 7.5). Plain
Python 3.11.

The model answers with blocks like this (empty SEARCH = create a new file)::

    path/to/file.py
    <<<<<<< SEARCH
    exact lines from the file
    =======
    the new lines
    >>>>>>> REPLACE

Rules:
- SEARCH must match exactly one place. If it matches nowhere exactly, two tolerant matches are tried (trailing
  whitespace; the whole block indented differently). Each must also be unique.
- Python files must still compile after the edit.
- All blocks apply or none do (atomic).
- Every rejection says what to do next, because the error is fed back to the model.
"""

import difflib
import re
from dataclasses import dataclass, field

from workspace import JailError, Workspace

BLOCK = re.compile(r"^(?P<path>[^\n<>=]+?)[ \t]*\n<<<<<<< SEARCH\n(?P<search>.*?)^=======\n(?P<replace>.*?)"
                   r"^>>>>>>> REPLACE[ \t]*$", re.S | re.M)


class EditError(Exception):
    """An edit that was not applied; the message is written for the model to act on."""


@dataclass
class Edit:
    path: str
    search: str
    replace: str


@dataclass
class Applied:
    files: list[str]
    notes: list[str] = field(default_factory=list)


def parse(text: str) -> list[Edit]:
    edits = [Edit(m["path"].strip(), m["search"], m["replace"]) for m in BLOCK.finditer(text)]
    if not edits:
        raise EditError("no SEARCH/REPLACE block found. Write: the file path on its own line, then "
                        "'<<<<<<< SEARCH', the exact old lines, '=======', the new lines, '>>>>>>> REPLACE'.")
    return edits


def _tolerant(text: str, search: str, replace: str) -> tuple[str, str] | None:
    """Unique match ignoring trailing whitespace, or with the whole block at a different indentation."""
    lines, want = text.split("\n"), search.rstrip("\n").split("\n")
    n = len(want)
    hits = [i for i in range(len(lines) - n + 1)
            if [x.rstrip() for x in lines[i:i + n]] == [x.rstrip() for x in want]]
    if len(hits) == 1:
        i = hits[0]
        new = lines[:i] + replace.rstrip("\n").split("\n") + lines[i + n:]
        return "\n".join(new), "matched ignoring trailing whitespace"
    shifted = []
    for i in range(len(lines) - n + 1):
        window = lines[i:i + n]
        if [x.strip() for x in window] != [x.strip() for x in want]:
            continue
        deltas = {len(a) - len(a.lstrip()) - (len(b) - len(b.lstrip())) for a, b in zip(window, want, strict=True)
                  if b.strip()}
        if len(deltas) == 1:
            shifted.append((i, deltas.pop()))
    if len(shifted) == 1:
        i, delta = shifted[0]
        fix = [(" " * delta + x if delta > 0 else x[-delta:]) if x.strip() else x
               for x in replace.rstrip("\n").split("\n")]
        return "\n".join(lines[:i] + fix + lines[i + n:]), f"matched with indentation shifted by {delta}"
    return None


def apply(ws: Workspace, edits: list[Edit]) -> Applied:
    staged: dict[str, str] = {}
    notes: list[str] = []
    for e in edits:
        try:
            ws.path(e.path)
        except JailError as exc:
            raise EditError(f"{exc}. Edit files inside the workspace only.") from None
        exists = e.path in staged or ws.exists(e.path)
        text = staged.get(e.path, ws.read(e.path) if exists else "")
        if not e.search.strip():
            if exists and text.strip():
                raise EditError(f"{e.path} already exists; an empty SEARCH only creates new files. Quote the lines "
                                f"to replace in SEARCH.")
            staged[e.path] = e.replace
            continue
        if not exists:
            raise EditError(f"{e.path} does not exist. Use an empty SEARCH to create it, or check the path "
                            f"(files: {', '.join(ws.files('.py'))}).")
        count = text.count(e.search)
        if count == 1:
            staged[e.path] = text.replace(e.search, e.replace)
            continue
        if count > 1:
            raise EditError(f"SEARCH matches {count} places in {e.path}; add the surrounding lines so it matches "
                            f"exactly one.")
        tolerant = _tolerant(text, e.search, e.replace)
        if tolerant is None:
            first = next((x for x in e.search.split("\n") if x.strip()), "")
            close = difflib.get_close_matches(first, text.split("\n"), n=1, cutoff=0.5)
            hint = f" The closest line is: {close[0].strip()!r}." if close else ""
            raise EditError(f"SEARCH was not found in {e.path}.{hint} Copy the lines exactly as they are in the "
                            f"file (read it again first).")
        staged[e.path], note = tolerant
        notes.append(f"{e.path}: {note}")
    for path, text in staged.items():
        if path.endswith(".py"):
            try:
                compile(text, path, "exec")
            except SyntaxError as exc:
                raise EditError(f"the edit would break {path}: SyntaxError on line {exc.lineno}: {exc.msg}. "
                                f"Nothing was changed; send a corrected edit.") from None
    for path, text in staged.items():
        ws.write(path, text)
    return Applied(sorted(staged), notes)


def apply_text(ws: Workspace, model_output: str) -> Applied:
    return apply(ws, parse(model_output))
