"""JavaScript / TypeScript facts (Sprint 9 stretch: multi-language inspector). Regular expressions over the source,
not a full parser: ES ``import`` / ``require`` (relative ones resolved to the repository's files), functions and
classes (``function f``, ``export function``, ``const f = (...) =>``, ``class C``), Express / Fastify / Koa-router
routes (``app.get("/x", ...)``), ``process.env.X``, ``listen(3000)`` ports and test files (``*.test.js``,
``__tests__/``). Comments are removed first, so commented-out code is not a fact.
"""

import posixpath
import re

from hmap.agents.docgen.inspect.python import RepoBits
from hmap.agents.docgen.model import ModuleFacts, Route, Symbol

JS_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts")
COMMENTS = re.compile(r"/\*.*?\*/|(?<![:\"'`])//[^\n]*", re.S)
IMPORT = re.compile(r"""(?:import\s+(?:[\w*{}\s,]+\s+from\s+)?|require\(\s*|import\(\s*)["']([^"']+)["']""")
FUNC = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)",
                  re.M)
ARROW = re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?"
                   r"(?:\(([^)]*)\)|[\w$]+)\s*=>", re.M)
CLASS = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.M)
ROUTE = re.compile(r"""\b(\w+)\.(get|post|put|patch|delete)\(\s*["'`](/[^"'`]*)["'`]""")
ENV = re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)|process\.env\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]")
LISTEN = re.compile(r"\.listen\(\s*(\d{2,5})|\bPORT\b[^\n=]*=\s*(?:[^\n]*\|\|\s*)?(\d{2,5})")


def is_js(path: str) -> bool:
    return path.endswith(JS_SUFFIXES) and not path.endswith(".d.ts")


def is_js_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return bool(re.search(r"\.(test|spec)\.[mc]?[jt]sx?$", name)) or "/__tests__/" in f"/{path}"


def resolve(from_path: str, spec: str, files: set[str]) -> str | None:
    if not spec.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), spec))
    for cand in (base, *(base + s for s in JS_SUFFIXES), *(f"{base}/index{s}" for s in JS_SUFFIXES)):
        if cand in files:
            return cand
    return None


def module_facts(rel: str, text: str, files: set[str]) -> tuple[ModuleFacts, RepoBits]:
    code = COMMENTS.sub("", text)
    mod = ModuleFacts(path=rel, module=re.sub(r"\.[^.]+$", "", rel).replace("/", "."),
                      lines=text.count("\n") + (0 if text.endswith("\n") else 1))
    bits = RepoBits()
    for m in IMPORT.finditer(code):
        spec = m.group(1)
        target = resolve(rel, spec, files)
        if target:
            mod.local_imports.append(target)
        else:
            mod.imports.append(spec.split("/")[1] if spec.startswith("@") and "/" in spec else spec.split("/")[0])
    for rx, kind in ((FUNC, "function"), (ARROW, "function"), (CLASS, "class")):
        for m in rx.finditer(code):
            name = m.group(1)
            line = code.count("\n", 0, m.start()) + 1
            params = m.group(2) if kind == "function" and m.lastindex and m.lastindex >= 2 else None
            sig = f"function {name}({params or ''})" if kind == "function" else f"class {name}"
            mod.symbols.append(Symbol(name=name, kind=kind, line=line, signature=sig,
                                      public=not name.startswith("_")))
            (mod.functions if kind == "function" else mod.classes).append(name)
    for m in ROUTE.finditer(code):
        bits.routes.append(Route(method=m.group(2).upper(), path=m.group(3), file=rel, function=f"{m.group(1)}|",
                                 line=code.count("\n", 0, m.start()) + 1))
    for m in ENV.finditer(code):
        bits.env.setdefault(m.group(1) or m.group(2), None)
    for m in LISTEN.finditer(code):
        port = int(m.group(1) or m.group(2))
        if 1 <= port <= 65535:
            bits.ports.append(port)
    if is_js_test(rel):
        bits.test_functions += len(re.findall(r"\b(?:it|test)\(\s*[\"'`]", code))
    mod.imports = sorted(set(mod.imports))
    mod.local_imports = sorted(set(mod.local_imports) - {rel})
    return mod, bits
