"""Plan metrics (spec item 3.14). See ``samples/planning/gold/references.py`` for the reference format.

- **validity**: the shipped plan passes every hard check (acyclic, one sink = review, known capabilities and ids,
  criteria); ``repairs`` counts what the validator had to fix to get there;
- **coverage**: requirements covered by a build / test / document step or flagged, over all requirements;
- **flags**: precision / recall of the flagged requirements against the reference;
- **step matching**: generated build / test / document steps matched one-to-one to reference steps (same phase,
  best requirement overlap; spine steps by id); precision / recall of the matching;
- **dependencies**: precision / recall / F1 of "A comes before B" (transitive closure) between matched steps;
- **must-edge recall**: share of the reference's must-have dependencies (plus the generic ones) the plan satisfies;
- **invented capabilities**: steps whose capability is not in the whitelist (must be 0).
"""

from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from hmap.agents.planning.templates import PLAN_CAPABILITIES
from hmap.agents.planning.validate import WORK_PHASES, check, errors, graph_of
from hmap.core.contracts.domain import PlanTask, RequirementSet, TaskGraph

SPINE_KEYS = ("research", "verify", "design", "review")


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: "PRF") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class PlanScore:
    case: str
    valid: bool
    repairs: int
    coverage: float
    uncovered: list[str]
    flags: PRF
    steps: PRF
    deps: PRF
    must_total: int
    must_ok: int
    must_missed: list[str]
    invented: int
    tasks: int
    seconds: float
    kind_ok: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if not isinstance(v, PRF)}
        for name in ("flags", "steps", "deps"):
            prf: PRF = getattr(self, name)
            out[name] = {"precision": round(prf.precision, 3), "recall": round(prf.recall, 3), "f1": round(prf.f1, 3),
                         "tp": prf.tp, "fp": prf.fp, "fn": prf.fn}
        return out


def _closure(g: "nx.DiGraph[str]") -> set[tuple[str, str]]:
    return {(a, b) for a in g.nodes for b in nx.descendants(g, a)}


def match_steps(tasks: list[PlanTask], ref_steps: dict[str, tuple[str, list[str], list[str]]]) -> dict[str, str]:
    """generated task id -> reference key (one-to-one)."""
    out: dict[str, str] = {}
    for key in SPINE_KEYS:
        if key in ref_steps and any(t.id == key for t in tasks):
            out[key] = key
    pairs: list[tuple[float, str, str]] = []
    for t in tasks:
        if t.id in out:
            continue
        for key, (phase, reqs, _) in ref_steps.items():
            if key in SPINE_KEYS or phase != t.phase:
                continue
            a, b = set(t.requirement_ids), set(reqs)
            score = len(a & b) / len(a | b) if a | b else 0.5  # document steps (no requirements): any match
            if score > 0:
                pairs.append((score, t.id, key))
    used_t: set[str] = set()
    used_k: set[str] = set(out.values())
    for _score, tid, key in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
        if tid in used_t or key in used_k:
            continue
        out[tid] = key
        used_t.add(tid)
        used_k.add(key)
    return out


def _select(tasks: list[PlanTask], selector: str) -> list[str]:
    if selector.startswith(("build:", "test:")):
        kind, rid = selector.split(":", 1)
        phase = "implement" if kind == "build" else "test"
        return [t.id for t in tasks if t.phase == phase and rid in t.requirement_ids]
    if selector == "document":
        return [t.id for t in tasks if t.phase == "document"]
    if selector == "builds":
        return [t.id for t in tasks if t.phase == "implement"]
    if selector == "tests":
        return [t.id for t in tasks if t.phase == "test"]
    if selector == "all":
        return [t.id for t in tasks if t.id != "review"]
    return [t.id for t in tasks if t.id == selector]


def must_edges(rs: RequirementSet, specific: list[tuple[str, str]]) -> list[tuple[str, str]]:
    generic = [("research", "design"), ("design", "builds"), ("tests", "document"), ("all", "review")]
    generic += [(f"build:{r.id}", f"test:{r.id}") for r in rs.requirements]
    return generic + list(specific)


def satisfied(tasks: list[PlanTask], g: "nx.DiGraph[str]", before: str, after: str) -> bool | None:
    """None when the plan has no step for one side (not applicable, e.g. a flagged requirement)."""
    a, b = _select(tasks, before), _select(tasks, after)
    if not a or not b:
        return None
    if before in ("tests", "all", "builds"):   # every step on the left must come before every step on the right
        return all(x == y or nx.has_path(g, x, y) for x in a for y in b)
    return all(any(x == y or nx.has_path(g, x, y) for x in a) for y in b)


def score_plan(case: str, rs: RequirementSet, graph: TaskGraph, reference: dict[str, Any], *,
               flagged: dict[str, str], repairs: int, seconds: float,
               kind: str | None = None) -> PlanScore:
    tasks = list(graph.tasks)
    g = graph_of(tasks)
    hard = errors(check(tasks, rs, flagged=flagged))
    valid = not [i for i in hard if i.code != "uncovered"]
    covered = {r for t in tasks if t.phase in WORK_PHASES for r in t.requirement_ids} | set(flagged)
    uncovered = [r.id for r in rs.requirements if r.id not in covered]
    ref_flags = set(reference.get("flagged", []))
    got_flags = set(flagged)
    flags = PRF(tp=len(ref_flags & got_flags), fp=len(got_flags - ref_flags), fn=len(ref_flags - got_flags))

    ref_steps: dict[str, tuple[str, list[str], list[str]]] = reference["steps"]
    mapping = match_steps(tasks, ref_steps)
    work_gen = [t.id for t in tasks if t.id not in SPINE_KEYS]
    work_ref = [k for k in ref_steps if k not in SPINE_KEYS]
    matched_gen = [t for t in work_gen if t in mapping]
    steps = PRF(tp=len(matched_gen), fp=len(work_gen) - len(matched_gen), fn=len(work_ref) - len(matched_gen))

    ref_g: nx.DiGraph[str] = nx.DiGraph()
    ref_g.add_nodes_from(ref_steps)
    for key, (_, _, after) in ref_steps.items():
        for a in after:
            ref_g.add_edge(a, key)
    ref_closure = _closure(ref_g)
    gen_closure = _closure(g)
    matched_keys = set(mapping.values())
    gen_pairs = {(mapping[a], mapping[b]) for a, b in gen_closure if a in mapping and b in mapping
                 and mapping[a] != mapping[b]}
    ref_pairs = {(a, b) for a, b in ref_closure if a in matched_keys and b in matched_keys}
    deps = PRF(tp=len(gen_pairs & ref_pairs), fp=len(gen_pairs - ref_pairs), fn=len(ref_pairs - gen_pairs))

    total = ok = 0
    missed: list[str] = []
    for before_sel, after_sel in must_edges(rs, reference.get("must", [])):
        result = satisfied(tasks, g, before_sel, after_sel)
        if result is None:
            continue
        total += 1
        if result:
            ok += 1
        else:
            missed.append(f"{before_sel} -> {after_sel}")
    invented = sum(1 for t in tasks if t.agent_capability not in PLAN_CAPABILITIES)
    return PlanScore(case=case, valid=valid, repairs=repairs, coverage=round(
        1 - len(uncovered) / max(1, len(rs.requirements)), 3), uncovered=uncovered, flags=flags, steps=steps,
        deps=deps, must_total=total, must_ok=ok, must_missed=missed, invented=invented, tasks=len(tasks),
        seconds=round(seconds, 2), kind_ok=kind is None or reference.get("kind", "software") == kind)
