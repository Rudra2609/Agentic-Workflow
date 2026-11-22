"""Architecture extractor (Sprint 9 item 9.2, plan D4): import graph -> components -> Mermaid.

Small repositories: one node per module. Larger ones: modules are folded into their package at the deepest level
that keeps at most ``MAX_NODES`` nodes (C4 "component" level). Every edge of the diagram is an import that exists in
the code (:func:`check_edges` proves it in the tests); declared libraries the code imports are drawn as externals,
compose services as infrastructure. The model only writes the narrative around it (``generate.py``).
"""

import re
from dataclasses import dataclass, field

import networkx as nx

from hmap.agents.docgen.model import Facts, ModuleFacts

MAX_NODES = 40
MERMAID_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class Component:
    id: str
    label: str
    modules: list[str] = field(default_factory=list)
    lines: int = 0
    entry: bool = False
    doc: str = ""


@dataclass
class Architecture:
    components: list[Component]
    edges: list[tuple[str, str, int]]                 # (from id, to id, number of module imports)
    externals: dict[str, list[str]]                   # library -> component ids that import it
    services: list[str]
    clusters: list[list[str]]                         # weakly connected groups of component ids
    folded: bool = False
    within: str | None = None

    def graph(self) -> dict[str, object]:
        """JSON for the UI (drawn with @xyflow/react)."""
        return {"nodes": [{"id": c.id, "label": c.label, "modules": len(c.modules), "lines": c.lines,
                           "entry": c.entry, "kind": "component"} for c in self.components]
                + [{"id": f"lib_{_safe(lib)}", "label": lib, "kind": "library"} for lib in self.externals]
                + [{"id": f"svc_{_safe(s)}", "label": s, "kind": "service"} for s in self.services],
                "edges": [{"from": a, "to": b, "count": n} for a, b, n in self.edges]
                + [{"from": c, "to": f"lib_{_safe(lib)}", "count": 1, "kind": "uses"}
                   for lib, comps in self.externals.items() for c in comps]}


def _safe(name: str) -> str:
    out = re.sub(r"\W", "_", name)
    return out if MERMAID_ID.fullmatch(out) else f"n_{out}"


def code_modules(facts: Facts, within: str | None = None) -> dict[str, ModuleFacts]:
    """The repository's code modules (no tests, no migrations, no data files that only look like modules: a ``.py``
    inside a package tree whose own folder is not a package, e.g. a project template)."""
    packages = {p.rsplit("/", 1)[0] for p in facts.modules if p.endswith("/__init__.py")}
    out = {}
    for m in facts.code_modules():
        parts = m.path.removesuffix(".py").split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        root = parts[: len(parts) - len(m.module.split("."))]       # the folder its dotted name starts in
        if any("/".join(root[:i]) in packages for i in range(1, len(root) + 1)):
            continue
        if "/versions/" in f"/{m.path}" or "/migrations/" in f"/{m.path}":
            continue
        if within and not (m.module == within or m.module.startswith(within + ".")):
            continue
        out[m.path] = m
    return out


def module_graph(facts: Facts, within: str | None = None) -> nx.DiGraph:
    g: nx.DiGraph = nx.DiGraph()
    code = code_modules(facts, within)
    for path in code:
        g.add_node(path)
    for path, m in code.items():
        for dep in m.local_imports:
            if dep in code and dep != path:
                g.add_edge(path, dep)
    return g


def extract(facts: Facts, max_nodes: int = MAX_NODES, within: str | None = None) -> Architecture:
    """Components at the deepest package level with at most ``max_nodes`` nodes; ``within`` = only that package
    (the detail diagram of one component)."""
    code = code_modules(facts, within)
    g = module_graph(facts, within)
    floor = len(within.split(".")) + 1 if within else 1
    base = {p: m.module for p, m in code.items()}
    if len(base) > max_nodes:      # loose scripts (not in a package) are grouped by their folder: scripts/, infra/...
        base = {p: (p.rsplit("/", 1)[0] + "/" if "." not in m.module and "/" in p
                    and not p.endswith("__init__.py") else m.module) for p, m in code.items()}
    depth = max((len(k.split(".")) for k in base.values()), default=1)
    keys = dict(base)
    while depth > floor and len(set(keys.values())) > max_nodes:
        depth -= 1
        keys = {p: ".".join(k.split(".")[:depth]) for p, k in base.items()}
    folded = len(set(keys.values())) < len(code)
    comps: dict[str, Component] = {}
    for path, m in sorted(code.items()):
        key = keys[path]
        c = comps.setdefault(key, Component(id=_safe(key), label=key if folded else path))
        c.modules.append(path)
        c.lines += m.lines
        c.entry = c.entry or path in facts.entrypoints
        if not c.doc and m.doc and (m.path.endswith("__init__.py") or not folded):
            c.doc = m.doc.split("\n")[0][:200]
    for path, m in code.items():                       # a package without an __init__ docstring: first module's
        c = comps[keys[path]]
        if not c.doc and m.doc:
            c.doc = m.doc.split("\n")[0][:200]
    counts: dict[tuple[str, str], int] = {}
    for a, b in g.edges:
        ka, kb = comps[keys[a]].id, comps[keys[b]].id
        if ka != kb:
            counts[(ka, kb)] = counts.get((ka, kb), 0) + 1
    deps = {d.replace("-", "_").lower() for d in facts.dependencies}
    externals: dict[str, set[str]] = {}
    for path, m in code.items():
        for name in m.imports:
            if name.lower() in deps:
                externals.setdefault(name, set()).add(comps[keys[path]].id)
    cg: nx.DiGraph = nx.DiGraph()
    cg.add_nodes_from(c.id for c in comps.values())
    cg.add_edges_from(counts)
    clusters = sorted((sorted(c) for c in nx.weakly_connected_components(cg)), key=lambda c: (-len(c), c))
    return Architecture(components=list(comps.values()), edges=sorted((a, b, n) for (a, b), n in counts.items()),
                        externals={k: sorted(v) for k, v in sorted(externals.items())}, services=facts.services,
                        clusters=clusters, folded=folded, within=within)


def mermaid(arch: Architecture, *, externals: bool = True) -> str:
    lines = ["flowchart LR"]
    for c in arch.components:
        label = c.label.replace('"', "'")
        lines.append(f'  {c.id}(["{label}"])' if c.entry else f'  {c.id}["{label}"]')
    for a, b, _ in arch.edges:
        lines.append(f"  {a} --> {b}")
    if externals:
        for lib, comps in arch.externals.items():
            lib_id = f"lib_{_safe(lib)}"
            lines.append(f'  {lib_id}[("{lib}")]')
            lines += [f"  {c} -.-> {lib_id}" for c in comps]
    if arch.services:
        lines.append("  subgraph infrastructure")
        lines += [f'    svc_{_safe(s)}[("{s}")]' for s in arch.services]
        lines.append("  end")
    return "\n".join(lines) + "\n"


NODE_LINE = re.compile(r'^\s*([A-Za-z_]\w*)(\(\["[^"]*"\]\)|\["[^"]*"\]|\[\("[^"]*"\)\])\s*$')
EDGE_LINE = re.compile(r"^\s*([A-Za-z_]\w*)\s*(-->|-\.->)\s*([A-Za-z_]\w*)\s*$")


def parse_mermaid(text: str) -> tuple[set[str], list[tuple[str, str, str]]]:
    """A small grammar check for the subset we write: raises ``ValueError`` on any other line."""
    rows = [r for r in text.strip().splitlines() if r.strip()]
    if not rows or rows[0].strip() not in ("flowchart LR", "flowchart TD", "graph LR", "graph TD"):
        raise ValueError("a Mermaid flowchart must start with 'flowchart LR'")
    nodes: set[str] = set()
    edges: list[tuple[str, str, str]] = []
    for row in rows[1:]:
        if row.strip() in ("end",) or row.strip().startswith("subgraph "):
            continue
        if m := NODE_LINE.match(row):
            nodes.add(m.group(1))
        elif m := EDGE_LINE.match(row):
            edges.append((m.group(1), m.group(3), m.group(2)))
        else:
            raise ValueError(f"not valid in our Mermaid subset: {row.strip()!r}")
    unknown = {n for a, b, _ in edges for n in (a, b)} - nodes
    if unknown:
        raise ValueError(f"edges to undeclared nodes: {sorted(unknown)}")
    return nodes, edges


def check_edges(text: str, arch: Architecture, facts: Facts) -> list[str]:
    """Every solid edge of the diagram must be an import in the code (item 9.2 acceptance)."""
    _, edges = parse_mermaid(text)
    real = {(a, b) for a, b, _ in arch.edges}
    members = {c.id: set(c.modules) for c in arch.components}
    g = module_graph(facts, arch.within)
    bad = []
    for a, b, kind in edges:
        if kind != "-->":
            continue
        if (a, b) not in real or not any(g.has_edge(x, y) for x in members.get(a, ()) for y in members.get(b, ())):
            bad.append(f"{a} --> {b}")
    return bad


def render_doc(facts: Facts, arch: Architecture, details: dict[str, "Architecture"], narrative: str) -> str:
    """The architecture document: overview diagram, components, one detail diagram per package, libraries."""
    lines = [f"# Architecture: {facts.repo}", "", narrative, "", "## Components", "", "```mermaid",
             mermaid(arch).rstrip(), "```", ""]
    lines += ["| Component | Modules | Lines | What it is |", "|---|---|---|---|"]
    for c in arch.components:
        what = c.doc.replace("|", "/") if c.doc else ""
        lines.append(f"| `{c.label}` | {len(c.modules)} | {c.lines} | {what} |")
    lines.append("")
    if arch.edges:
        lines += ["Arrows are imports: `a --> b` means code in `a` imports `b` (every arrow is an import in the "
                  "code).", ""]
    for label, d in details.items():
        if len(d.components) < 2:
            continue
        lines += [f"## Inside `{label}`", "", "```mermaid", mermaid(d, externals=False).rstrip(), "```", ""]
        lines += [f"- `{c.label}`: {c.doc}" if c.doc else f"- `{c.label}`" for c in d.components]
        lines.append("")
    if arch.externals:
        lines += ["## Libraries", ""]
        lines += [f"- {lib} (declared {facts.dependencies.get(lib.lower().replace('_', '-'), '') or 'unpinned'}): "
                  f"used by {', '.join(f'`{_label(arch, c)}`' for c in comps)}"
                  for lib, comps in arch.externals.items()]
        lines.append("")
    if arch.services:
        lines += ["## Infrastructure", "", "Docker compose services: " + ", ".join(f"`{s}`" for s in arch.services)
                  + ".", ""]
    return "\n".join(lines).rstrip() + "\n"


def _label(arch: Architecture, cid: str) -> str:
    return next((c.label for c in arch.components if c.id == cid), cid)


def details(facts: Facts, arch: Architecture, limit: int = 12) -> dict[str, Architecture]:
    """Detail diagrams for the folded components with more than one module (largest first)."""
    if not arch.folded:
        return {}
    big = sorted((c for c in arch.components if len(c.modules) > 1), key=lambda c: (-len(c.modules), c.label))
    return {c.label: extract(facts, within=c.label) for c in big[:limit]}
