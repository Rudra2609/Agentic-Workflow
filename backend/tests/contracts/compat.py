"""JSON-Schema compatibility checker for the cross-member contracts.

Breaking (blocks): removed contract / property, new required property, property became required or optional,
type change, anyOf/oneOf change, removed enum/const value, array item type change.
Additive (must be accepted explicitly with `make contracts-snapshot`): new contract, new optional property,
new enum value.
"""

from dataclasses import dataclass
from typing import Any

# contract -> (owner, consumers) — doc 01 §4
OWNERS: dict[str, tuple[str, str]] = {
    "RequirementSet": ("Member 2", "Member 3, Member 10"),
    "TaskGraph": ("Member 3", "Manager (Member 1), all agents"),
    "RefinementSpec": ("Member 4", "any agent using the Refiner"),
    "RefinementTrace": ("Member 4", "any agent using the Refiner, UI"),
    "ResearchBrief": ("Member 1 (Manager)", "Member 5"),
    "ResearchReport": ("Member 5", "Member 6, Member 10"),
    "VerificationReport": ("Member 6", "Manager, Member 10"),
    "CodeChangeSet": ("Member 7", "Member 8, Member 9, Member 10"),
    "TestReport": ("Member 8", "Member 7, Member 10"),
    "DocBundle": ("Member 9", "Member 10"),
    "ReviewReport": ("Member 10", "Manager (Member 1)"),
    "ModelSpec": ("Member 11", "everyone"),
    "RouteDecision": ("Member 11", "everyone"),
    "BenchmarkResult": ("Member 11", "everyone"),
}


def owner_of(schema_file: str) -> tuple[str, str]:
    name = schema_file.split("/")[-1].removesuffix(".schema.json")
    if schema_file.startswith("domain/"):
        return OWNERS.get(name, ("unknown", "unknown"))
    return ("Member 1", "everyone (message/envelope/event layer)")


@dataclass
class Change:
    kind: str  # "breaking" | "additive"
    where: str
    what: str


def _deref(node: Any, defs: dict[str, Any]) -> Any:
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 20:
        node = defs.get(node["$ref"].split("/")[-1], {})
        seen += 1
    return node


def _sig(node: Any, defs: dict[str, Any]) -> str:
    node = _deref(node, defs)
    if not isinstance(node, dict):
        return repr(node)
    if "anyOf" in node or "oneOf" in node:
        return "|".join(sorted(_sig(n, defs) for n in node.get("anyOf", node.get("oneOf", []))))
    if "enum" in node or "const" in node:
        return f"{node.get('type', 'any')}:enum"
    return str(node.get("type", "object" if "properties" in node else "any"))


def compare(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    out: list[Change] = []
    od, nd = old.get("$defs", {}), new.get("$defs", {})
    visited: set[tuple[str, str]] = set()

    def walk(o: Any, n: Any, where: str) -> None:
        key = (where, repr(o)[:200])
        if key in visited:
            return
        visited.add(key)
        o, n = _deref(o, od), _deref(n, nd)
        if not isinstance(o, dict) or not isinstance(n, dict):
            return
        if _sig(o, od) != _sig(n, nd):
            out.append(Change("breaking", where, f"type changed {_sig(o, od)} -> {_sig(n, nd)}"))
            return
        for k in ("anyOf", "oneOf"):
            if k in o:
                for i, (oo, nn) in enumerate(zip(o[k], n.get(k, []), strict=False)):
                    walk(oo, nn, f"{where}<{k}{i}>")
        ov = set(map(repr, o.get("enum", []))) | ({repr(o["const"])} if "const" in o else set())
        nv = set(map(repr, n.get("enum", []))) | ({repr(n["const"])} if "const" in n else set())
        if ov - nv:
            out.append(Change("breaking", where, f"allowed values removed: {sorted(ov - nv)}"))
        if nv - ov and ov:
            out.append(Change("additive", where, f"allowed values added: {sorted(nv - ov)}"))
        op, np_ = o.get("properties", {}), n.get("properties", {})
        oreq, nreq = set(o.get("required", [])), set(n.get("required", []))
        for prop in sorted(set(op) | set(np_)):
            p = f"{where}.{prop}"
            if prop not in np_:
                out.append(Change("breaking", p, "property removed"))
            elif prop not in op:
                out.append(Change("breaking" if prop in nreq else "additive", p,
                                  "new REQUIRED property" if prop in nreq else "new optional property"))
            else:
                if (prop in oreq) != (prop in nreq):
                    out.append(Change("breaking", p, "became required" if prop in nreq else "became optional"))
                walk(op[prop], np_[prop], p)
        if "items" in o or "items" in n:
            walk(o.get("items", {}), n.get("items", {}), f"{where}[]")
        if isinstance(o.get("additionalProperties"), dict) and isinstance(n.get("additionalProperties"), dict):
            walk(o["additionalProperties"], n["additionalProperties"], f"{where}{{}}")

    walk(old, new, "$")
    return out
