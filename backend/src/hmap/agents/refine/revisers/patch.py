"""JSON-pointer patches (RFC 6901 paths; ``add`` / ``replace`` / ``remove`` like RFC 6902) on plain JSON values.

``apply`` never mutates its input: it deep-copies only the containers on the path it changes, so every part of the
document a patch does not touch keeps its exact value (the targeted reviser's "unflagged parts stay byte-identical"
guarantee is tested on this).
"""

import copy
import json
from dataclasses import dataclass
from typing import Any, Literal

Op = Literal["add", "replace", "remove"]


class PatchError(ValueError):
    pass


@dataclass(frozen=True)
class Patch:
    op: Op
    path: str
    value: Any = None


def parts(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise PatchError(f"not a JSON path: {path!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def resolve(doc: Any, path: str) -> Any:
    node = doc
    for p in parts(path):
        if isinstance(node, list):
            try:
                node = node[int(p)]
            except (ValueError, IndexError) as exc:
                raise PatchError(f"{path}: no item {p}") from exc
        elif isinstance(node, dict):
            if p not in node:
                raise PatchError(f"{path}: no key {p}")
            node = node[p]
        else:
            raise PatchError(f"{path}: cannot descend into a {type(node).__name__}")
    return node


def exists(doc: Any, path: str) -> bool:
    try:
        resolve(doc, path)
    except PatchError:
        return False
    return True


def apply(doc: Any, patch: Patch) -> Any:
    """A new document with ``patch`` applied (``add`` with a last segment ``-`` appends to a list)."""
    keys = parts(patch.path)
    if not keys:
        if patch.op == "remove":
            raise PatchError("cannot remove the whole document")
        return copy.deepcopy(patch.value)
    root = _shallow(doc)
    node = root
    for p in keys[:-1]:
        if isinstance(node, list):
            idx = _index(node, p, patch.path)
            node[idx] = _shallow(node[idx])
            node = node[idx]
        elif isinstance(node, dict):
            if p not in node:
                raise PatchError(f"{patch.path}: no key {p}")
            node[p] = _shallow(node[p])
            node = node[p]
        else:
            raise PatchError(f"{patch.path}: cannot descend into a {type(node).__name__}")
    last = keys[-1]
    value = copy.deepcopy(patch.value)
    if isinstance(node, list):
        if patch.op == "add":
            if last == "-":
                node.append(value)
            else:
                node.insert(_index(node, last, patch.path, allow_end=True), value)
        elif patch.op == "replace":
            node[_index(node, last, patch.path)] = value
        else:
            del node[_index(node, last, patch.path)]
    elif isinstance(node, dict):
        if patch.op == "replace" and last not in node:
            raise PatchError(f"{patch.path}: nothing to replace")
        if patch.op == "remove":
            if last not in node:
                raise PatchError(f"{patch.path}: nothing to remove")
            del node[last]
        else:
            node[last] = value
    else:
        raise PatchError(f"{patch.path}: parent is not a container")
    return root


def apply_all(doc: Any, patches: list[Patch]) -> Any:
    out = doc
    for p in patches:
        out = apply(out, p)
    return out


def within(path: str, scope: str) -> bool:
    """``path`` is ``scope`` or below it (``/a/1/b`` is within ``/a/1``; ``/a/-`` is within ``/a``)."""
    if scope in ("", "/"):
        return True
    scope = scope.rstrip("/")
    return path == scope or path.startswith(scope + "/")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _shallow(node: Any) -> Any:
    if isinstance(node, dict):
        return dict(node)
    if isinstance(node, list):
        return list(node)
    return node


def _index(node: list[Any], p: str, path: str, *, allow_end: bool = False) -> int:
    try:
        idx = int(p)
    except ValueError as exc:
        raise PatchError(f"{path}: {p!r} is not a list index") from exc
    upper = len(node) if allow_end else len(node) - 1
    if idx < 0 or idx > upper:
        raise PatchError(f"{path}: index {idx} out of range")
    return idx
