"""Exports (Sprint 9 stretch): the architecture graph as SVG, every document as one static HTML page (docs-as-site,
no build tool, no JavaScript), the changelog between two sets of facts, and a docstring patch.

All output is built from escaped text: a document is model-written Markdown, so nothing in it may become markup.
"""

import ast
import difflib
import html
import re
from typing import Any

from hmap.agents.docgen.model import Facts

NODE_W, NODE_H, GAP_X, GAP_Y = 190, 44, 60, 22


# ------------------------------------------------------------------------------------------------- SVG


def layout(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Columns by import depth (components), libraries and services last; the same layout as the Docs tab."""
    level = {n["id"]: 0 for n in nodes}
    comp = [e for e in edges if e.get("kind") != "uses"]
    for _ in range(len(nodes)):
        moved = False
        for e in comp:
            want = level.get(e["from"], 0) + 1
            if want > level.get(e["to"], 0) and want < len(nodes):
                level[e["to"]] = want
                moved = True
        if not moved:
            break
    last = max([level[n["id"]] for n in nodes if n.get("kind") == "component"], default=0) + 1
    for n in nodes:
        if n.get("kind") != "component":
            level[n["id"]] = last
    rows: dict[int, int] = {}
    pos = {}
    for n in nodes:
        col = level[n["id"]]
        pos[n["id"]] = (20 + col * (NODE_W + GAP_X), 20 + rows.get(col, 0) * (NODE_H + GAP_Y))
        rows[col] = rows.get(col, 0) + 1
    return pos


def svg(graph: dict[str, Any], title: str = "Architecture") -> str:
    nodes, edges = list(graph.get("nodes") or []), list(graph.get("edges") or [])
    pos = layout(nodes, edges)
    width = max((x for x, _ in pos.values()), default=0) + NODE_W + 40
    height = max((y for _, y in pos.values()), default=0) + NODE_H + 40
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           f'font-family="Helvetica, Arial, sans-serif" font-size="12">',
           f"<title>{html.escape(title)}</title>",
           '<defs><marker id="a" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" '
           'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#555"/></marker></defs>',
           '<rect width="100%" height="100%" fill="#ffffff"/>']
    for e in edges:
        if e["from"] not in pos or e["to"] not in pos:
            continue
        (x1, y1), (x2, y2) = pos[e["from"]], pos[e["to"]]
        dash = ' stroke-dasharray="4 3"' if e.get("kind") == "uses" else ""
        out.append(f'<line x1="{x1 + NODE_W}" y1="{y1 + NODE_H // 2}" x2="{x2}" y2="{y2 + NODE_H // 2}" '
                   f'stroke="#555" stroke-width="1"{dash} marker-end="url(#a)"/>')
    fill = {"component": "#f4f1ea", "library": "#eef2f7", "service": "#e8f3ec"}
    for n in nodes:
        x, y = pos[n["id"]]
        label = html.escape(str(n.get("label", n["id"]))[:28])
        sub = (f'{n.get("modules", 0)} module(s)' if n.get("kind") == "component" else str(n.get("kind")))
        colour = fill.get(str(n.get("kind")), "#fff")
        out.append(f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="6" fill="{colour}" stroke="#888"/>')
        out.append(f'<text x="{x + 8}" y="{y + 18}" fill="#111">{label}</text>')
        out.append(f'<text x="{x + 8}" y="{y + 34}" fill="#666" font-size="10">{html.escape(sub)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------- docs-as-site


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                  lambda m: f'<a href="{html.escape(m.group(2))}" rel="noreferrer">{m.group(1)}</a>', text)


def markdown_html(md: str) -> str:
    """A small Markdown -> HTML converter for our own documents (headings, lists, tables, code); everything escaped."""
    out: list[str] = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.lstrip().startswith("```"):
            lang = line.strip()[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                body.append(lines[i])
                i += 1
            cls = f' class="lang-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre{cls}><code>{html.escape(chr(10).join(body))}</code></pre>")
        elif m := re.match(r"^(#{1,6})\s+(.*)$", line):
            n = len(m.group(1))
            anchor = re.sub(r"[^a-z0-9]+", "-", m.group(2).lower()).strip("-")
            out.append(f'<h{n} id="{anchor}">{_inline(m.group(2))}</h{n}>')
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[\s:|-]+\|?$", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            i -= 1
            if rows:
                head = "".join(f"<th>{_inline(c)}</th>" for c in rows[0])
                cells = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{cells}</tbody></table>")
        elif re.match(r"^\s*([-*]|\d+\.)\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                item = re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i])
                items.append(f"<li>{_inline(item)}</li>")
                i += 1
            i -= 1
            out.append("<ul>" + "".join(items) + "</ul>")
        elif line.strip():
            para = [line.strip()]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#|\||```|\s*[-*]\s|\s*\d+\.\s)",
                                                                                lines[i + 1]):
                i += 1
                para.append(lines[i].strip())
            out.append(f"<p>{_inline(' '.join(para))}</p>")
        i += 1
    return "\n".join(out)


STYLE = ("body{font:15px/1.55 system-ui,sans-serif;max-width:60rem;margin:0 auto;padding:1rem 1.25rem;color:#1d1d1f}"
         "nav{position:sticky;top:0;background:#fff;padding:.5rem 0;border-bottom:1px solid #ddd}"
         "nav a{margin-right:1rem}"
         "pre{background:#f5f5f5;padding:.75rem;overflow:auto;border-radius:6px}code{font:13px ui-monospace,monospace}"
         "table{border-collapse:collapse;display:block;overflow:auto}td,th{border:1px solid #ddd;padding:.25rem .5rem;"
         "text-align:left;vertical-align:top}section{margin-top:2.5rem}h1{font-size:1.6rem}")


def site(docs: dict[str, str], title: str, graph_svg: str | None = None) -> str:
    """Every document on one static page with a navigation bar; the architecture SVG inline (it is our own SVG)."""
    order = [n for n in ("readme", "api", "architecture", "summaries", "report") if n in docs]
    labels = {"readme": "README", "api": "API", "architecture": "Architecture", "summaries": "Code", "report": "Report"}
    nav = "".join(f'<a href="#doc-{n}">{labels[n]}</a>' for n in order)
    parts = []
    for n in order:
        extra = graph_svg if n == "architecture" and graph_svg else ""
        parts.append(f'<section id="doc-{n}">{extra}{markdown_html(docs[n])}</section>')
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>"
            f"<nav>{nav}</nav>{''.join(parts)}</body></html>\n")


# ------------------------------------------------------------------------------------------- changelog


def changelog(old: Facts, new: Facts) -> list[str]:
    """What changed in the code between two documentation runs, as plain sentences (for docs.update)."""
    out: list[str] = []

    def diff(label: str, a: set[str], b: set[str]) -> None:
        def code(x: str) -> str:                     # "--max-clients\tserver.py" -> `--max-clients` (server.py)
            name, _, where = x.partition("\t")
            return f"`{name}`" + (f" ({where})" if where else "")
        if b - a:
            out.append(f"Added {label}: " + ", ".join(code(x) for x in sorted(b - a)[:15]) + ".")
        if a - b:
            out.append(f"Removed {label}: " + ", ".join(code(x) for x in sorted(a - b)[:15]) + ".")

    diff("endpoints", {f"{r.method} {r.path}" for r in old.routes}, {f"{r.method} {r.path}" for r in new.routes})
    diff("command-line options", {f"{f}\t{p}" for p, fl in old.cli.items() for f in fl},
         {f"{f}\t{p}" for p, fl in new.cli.items() for f in fl})
    diff("environment variables", set(old.env), set(new.env))
    diff("dependencies", set(old.dependencies), set(new.dependencies))
    diff("modules", set(old.modules), set(new.modules))
    diff("functions and classes", {f"{p}::{s.name}" for p, s in old.public_symbols()},
         {f"{p}::{s.name}" for p, s in new.public_symbols()})
    if set(old.ports) != set(new.ports):
        out.append(f"Ports: {', '.join(map(str, old.ports)) or 'none'} -> {', '.join(map(str, new.ports)) or 'none'}.")
    if len(old.tests) != len(new.tests):
        out.append(f"Test files: {len(old.tests)} -> {len(new.tests)}.")
    return out


# ------------------------------------------------------------------------------------ docstring write-back


def docstring_patch(files: dict[str, str], summaries: list[Any]) -> str:
    """A unified diff that adds the model's summaries as docstrings to public functions / classes that have none.
    Offered for review only (never applied by the agent). ``summaries``: ``SymbolSummary`` items with ``by="model"``."""
    by_file: dict[str, dict[str, str]] = {}
    for s in summaries:
        if getattr(s, "by", "") == "model" and s.summary and not s.summary.startswith("`"):
            by_file.setdefault(s.path, {})[s.name.split(".")[-1]] = s.summary
    patches = []
    for path, wanted in sorted(by_file.items()):
        text = files.get(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        lines = text.split("\n")
        inserts: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.name in wanted \
                    and ast.get_docstring(node) is None and node.body:
                first = node.body[0]
                indent = " " * first.col_offset
                doc = wanted[node.name].replace('"""', "'''").replace("\\", "\\\\")
                inserts.append((first.lineno - 1, f'{indent}"""{doc}"""'))
        if not inserts:
            continue
        new = list(lines)
        for at, line in sorted(inserts, reverse=True):
            new.insert(at, line)
        patches.append("".join(difflib.unified_diff([x + "\n" for x in lines], [x + "\n" for x in new],
                                                    fromfile=f"a/{path}", tofile=f"b/{path}")))
    return "".join(patches)
