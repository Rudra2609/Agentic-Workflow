"""SEARCH/REPLACE edit applicator (Sprint 7 item 7.5, plan D13; ported from ``samples/coding/edits.py``).

The model answers with blocks like this (an empty SEARCH creates a new file)::

    path/to/file.py
    <<<<<<< SEARCH
    exact lines from the file
    =======
    the new lines
    >>>>>>> REPLACE

Rules: SEARCH must match exactly one place; if it matches nowhere exactly, two tolerant matches are tried (trailing
whitespace; the whole block indented differently), each of which must also be unique. Python files must still
compile. All blocks apply or none do (atomic). Every rejection says what to do next: it goes back to the model.
"""

import difflib
import re
from dataclasses import dataclass, field

from hmap.agents.coding.workspace import JailError, Workspace, WorkspaceTooLarge, skipped

BLOCK = re.compile(r"^(?P<path>[^\n<>=]+?)[ \t]*\n(?:```[\w+-]*\n)?<<<<<<< SEARCH[ \t]*\n(?P<search>.*?)"
                   r"^=======[ \t]*\n(?P<replace>.*?)^>>>>>>> REPLACE[ \t]*$", re.S | re.M)
FORMAT_HELP = ("Write each edit as: the file path on its own line, then '<<<<<<< SEARCH', the exact old lines, "
               "'=======', the new lines, '>>>>>>> REPLACE'. An empty SEARCH creates a new file.")


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


def _clean_path(raw: str) -> str:
    path = raw.strip().strip("`*").strip()
    for prefix in ("File:", "file:", "Path:", "path:", "#"):
        if path.startswith(prefix):
            path = path[len(prefix):].strip()
    return path


def parse(text: str) -> list[Edit]:
    edits = [Edit(_clean_path(m["path"]), m["search"], m["replace"]) for m in BLOCK.finditer(text)]
    if not edits:
        raise EditError(f"no SEARCH/REPLACE block found. {FORMAT_HELP}")
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
            rel = ws.rel(e.path)
        except JailError as exc:
            raise EditError(f"{exc}. Edit files inside the workspace only.") from None
        if rel == "." or skipped(rel):
            raise EditError(f"{e.path} cannot be edited (.env files, caches and .git are not part of a workspace).")
        exists = rel in staged or ws.is_file(rel)
        try:
            text = staged.get(rel, ws.read(rel) if exists else "")
        except (ValueError, WorkspaceTooLarge) as exc:
            raise EditError(f"{rel} cannot be edited: {exc}") from None
        if not e.search.strip():
            if exists and text.strip():
                raise EditError(f"{rel} already exists; an empty SEARCH only creates new files. Quote the lines "
                                f"to replace in SEARCH.")
            staged[rel] = e.replace
            continue
        if not exists:
            listing = ", ".join(ws.files(".py")[:30])
            raise EditError(f"{rel} does not exist. Use an empty SEARCH to create it, or check the path "
                            f"(files: {listing}).")
        count = text.count(e.search)
        if count == 1:
            staged[rel] = text.replace(e.search, e.replace)
            continue
        if count > 1:
            raise EditError(f"SEARCH matches {count} places in {rel}; add the surrounding lines so it matches "
                            f"exactly one.")
        tolerant = _tolerant(text, e.search, e.replace)
        if tolerant is None:
            first = next((x for x in e.search.split("\n") if x.strip()), "")
            close = difflib.get_close_matches(first, text.split("\n"), n=1, cutoff=0.5)
            hint = f" The closest line is: {close[0].strip()!r}." if close else ""
            raise EditError(f"SEARCH was not found in {rel}.{hint} Copy the lines exactly as they are in the "
                            f"file (read it again first).")
        staged[rel], note = tolerant
        notes.append(f"{rel}: {note}")
    originals = {path: (ws.read(path) if ws.is_file(path) else None) for path in staged}
    staged = {path: text for path, text in staged.items() if text != originals[path]}
    if not staged:
        raise EditError("the edit changes nothing (REPLACE is the same as the current code). Change the code, or "
                        "answer NO CHANGES if nothing needs to change.")
    for path, text in staged.items():
        if path.endswith(".py"):
            try:
                compile(text, path, "exec")
            except SyntaxError as exc:
                raise EditError(f"the edit would break {path}: SyntaxError on line {exc.lineno}: {exc.msg}. "
                                f"Nothing was changed; send a corrected edit.") from None
    for path, text in staged.items():
        try:
            ws.write(path, text)
        except (JailError, WorkspaceTooLarge) as exc:
            raise EditError(f"{path}: {exc}") from None
    return Applied(sorted(staged), notes)


def apply_text(ws: Workspace, model_output: str) -> Applied:
    return apply(ws, parse(model_output))
