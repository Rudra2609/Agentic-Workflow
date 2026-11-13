"""Repository map (Sprint 7 item 7.2, plan D9): a compact, budgeted outline of the workspace for prompts.

Python files are parsed with ``ast`` (classes, functions, methods with their signatures, the first docstring line,
imports); other files are listed by name and size. Entries are cached by file content hash, so after an edit only the
changed file is parsed again. :meth:`RepoMap.render` cuts the outline to a token budget: the focus files (what the
locator found) get full detail, the others top-level names, then names only.
"""

import ast
import hashlib
from dataclasses import dataclass, field

from hmap.agents.coding.context_budget import tokens
from hmap.agents.coding.workspace import Workspace

_CACHE: dict[str, "FileEntry"] = {}
_CACHE_MAX = 4000


@dataclass
class FileEntry:
    path: str
    sha: str
    lines: int
    doc: str = ""
    symbols: list[str] = field(default_factory=list)     # "class Room", "  def broadcast(self, text, sender=None)"
    top: list[str] = field(default_factory=list)         # top-level names only
    imports: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py")


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:  # pragma: no cover - ast.unparse handles every valid tree
        args = "..."
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix} {node.name}({args}){ret}"


def _first_line(doc: str | None) -> str:
    return (doc or "").strip().split("\n", 1)[0][:100]


def parse_python(path: str, text: str) -> FileEntry:
    sha = hashlib.sha256(text.encode()).hexdigest()
    entry = FileEntry(path=path, sha=sha, lines=text.count("\n") + (0 if text.endswith("\n") else 1))
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        entry.error = f"SyntaxError line {exc.lineno}"
        return entry
    entry.doc = _first_line(ast.get_docstring(tree))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            entry.symbols.append(f"class {node.name}({bases})" if bases else f"class {node.name}")
            entry.top.append(node.name)
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                    entry.symbols.append("  " + _signature(sub))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            entry.symbols.append(_signature(node))
            entry.top.append(node.name)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id.isupper():
            entry.symbols.append(f"{node.targets[0].id} = …")
            entry.top.append(node.targets[0].id)
        elif isinstance(node, ast.Import):
            entry.imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            entry.imports.append(("." * node.level) + node.module)
    return entry


def symbol_lines(text: str) -> dict[str, tuple[int, int]]:
    """``{name: (first line, last line)}`` for top-level functions/classes and ``Class.method`` (1-based)."""
    out: dict[str, tuple[int, int]] = {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            out[node.name] = (node.lineno, node.end_lineno or node.lineno)
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                        out[f"{node.name}.{sub.name}"] = (sub.lineno, sub.end_lineno or sub.lineno)
    return out


@dataclass
class RepoMap:
    entries: dict[str, FileEntry]
    parsed: int = 0          # files parsed in this build (the rest came from the cache)

    @classmethod
    def build(cls, ws: Workspace, previous: "RepoMap | None" = None) -> "RepoMap":
        entries: dict[str, FileEntry] = {}
        parsed = 0
        for rel, text in ws.snapshot().items():
            sha = hashlib.sha256(text.encode()).hexdigest()
            old = previous.entries.get(rel) if previous else None
            if old is not None and old.sha == sha:
                entries[rel] = old
                continue
            cached = _CACHE.get(f"{rel}:{sha}")
            if cached is None:
                if rel.endswith(".py"):
                    cached = parse_python(rel, text)
                else:
                    cached = FileEntry(path=rel, sha=sha, lines=text.count("\n") + 1)
                parsed += 1
                if len(_CACHE) > _CACHE_MAX:
                    _CACHE.clear()
                _CACHE[f"{rel}:{sha}"] = cached
            entries[rel] = cached
        return cls(entries=dict(sorted(entries.items())), parsed=parsed)

    def _detail(self, e: FileEntry, level: int) -> str:
        head = f"{e.path} ({e.lines} lines)" + (f" — {e.doc}" if e.doc else "") + (f" [{e.error}]" if e.error else "")
        if level == 0 or not e.is_python:
            return head
        body = e.symbols if level == 2 else [s for s in e.symbols if not s.startswith("  ")]
        return "\n".join([head, *("    " + s for s in body)])

    def render(self, budget_tokens: int, focus: list[str] | tuple[str, ...] = ()) -> str:
        """The outline within ``budget_tokens``: focus files in full, the rest shortened as needed."""
        order = [p for p in focus if p in self.entries] + [p for p in self.entries if p not in focus]
        for levels in ((2, 1), (2, 0), (1, 0), (0, 0)):
            parts = [self._detail(self.entries[p], levels[0] if p in focus else levels[1]) for p in order]
            text = "\n".join(parts)
            if tokens(text) <= budget_tokens:
                return text
        out: list[str] = []
        used = 0
        for p in order:
            line = self._detail(self.entries[p], 0)
            if used + tokens(line) + 4 > budget_tokens:
                out.append(f"… {len(order) - len(out)} more files")
                break
            out.append(line)
            used += tokens(line) + 1
        return "\n".join(out)

    def search_text(self, path: str) -> str:
        """Identifiers + docstring for the locator (file name included)."""
        e = self.entries[path]
        return " ".join([path, e.doc, *e.symbols, *e.imports])
