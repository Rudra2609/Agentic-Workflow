"""Differences between two versions of an output, for the "what did this revision change" view (item 4.13).

Lists of objects that carry an ``id`` (requirements, plan steps) are matched by id, so a reordering is not a change;
everything else is compared position by position. Each change: ``{path, op: added|removed|changed, before, after}``
(``path`` uses item ids where it can: ``requirements/R7``, ``tasks/T5/depends_on``).
"""

from typing import Any

MAX_CHANGES = 200


def _keyed(items: list[Any]) -> dict[str, Any] | None:
    if items and all(isinstance(i, dict) and isinstance(i.get("id"), str) for i in items):
        keys = [i["id"] for i in items]
        if len(set(keys)) == len(keys):
            return {i["id"]: i for i in items}
    return None


def diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    _walk(a, b, path, out)
    return out[:MAX_CHANGES]


def _walk(a: Any, b: Any, path: str, out: list[dict[str, Any]]) -> None:
    if len(out) >= MAX_CHANGES or a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in [*a.keys(), *(k for k in b if k not in a)]:
            p = f"{path}/{k}" if path else str(k)
            if k not in b:
                out.append({"path": p, "op": "removed", "before": a[k], "after": None})
            elif k not in a:
                out.append({"path": p, "op": "added", "before": None, "after": b[k]})
            else:
                _walk(a[k], b[k], p, out)
        return
    if isinstance(a, list) and isinstance(b, list):
        ka, kb = _keyed(a), _keyed(b)
        if (ka is not None and kb is not None) or (ka is not None and not b) or (kb is not None and not a):
            ka, kb = ka or {}, kb or {}
            for k in [*ka.keys(), *(k for k in kb if k not in ka)]:
                p = f"{path}/{k}"
                if k not in kb:
                    out.append({"path": p, "op": "removed", "before": ka[k], "after": None})
                elif k not in ka:
                    out.append({"path": p, "op": "added", "before": None, "after": kb[k]})
                else:
                    _walk(ka[k], kb[k], p, out)
            return
        if all(not isinstance(x, dict | list) for x in [*a, *b]):
            gone = [x for x in a if x not in b]
            new = [x for x in b if x not in a]
            if gone or new:
                out.append({"path": path, "op": "changed", "before": a, "after": b,
                            "removed_items": gone, "added_items": new})
            return
        for i in range(max(len(a), len(b))):
            p = f"{path}/{i}"
            if i >= len(b):
                out.append({"path": p, "op": "removed", "before": a[i], "after": None})
            elif i >= len(a):
                out.append({"path": p, "op": "added", "before": None, "after": b[i]})
            else:
                _walk(a[i], b[i], p, out)
        return
    out.append({"path": path, "op": "changed", "before": a, "after": b})
