"""API documentation (Sprint 9 item 9.5, plan D6): one section per HTTP endpoint the code defines.

Source 1, always: the routes the AST found (method, path with router prefixes, parameters, request model,
``response_model``, docstring, handler). Source 2, when available: the app's own OpenAPI document. For a generated
project it is produced **inside the testing sandbox** (importing the app runs its code, plan T4); the platform's own
API (dogfood) comes from ``create_app().openapi()``. Endpoints in the document = endpoints in the code: the grounding
checker's ENDPOINT rule proves it.
"""

import json
import re
from typing import Any

from hmap.agents.docgen.model import Facts, Route
from hmap.core.tracing import get_logger

log = get_logger("hmap.docgen.api")

METHODS = ("get", "post", "put", "patch", "delete")
APP_ASSIGN = re.compile(r"^(\w+)\s*(?::\s*\w+)?\s*=\s*(?:fastapi\.)?FastAPI\(", re.M)
OPENAPI_SCRIPT = """import json, sys, importlib
sys.path.insert(0, ".")
mod = importlib.import_module(sys.argv[1])
app = getattr(mod, sys.argv[2])
print("HMAP_OPENAPI " + json.dumps(app.openapi()))
"""


def app_location(facts: Facts, files: dict[str, str]) -> tuple[str, str] | None:
    """(dotted module, variable) of a ``FastAPI()`` app assigned at module level."""
    for path, mod in sorted(facts.modules.items()):
        if "fastapi" not in mod.imports or path.startswith("tests/"):
            continue
        if m := APP_ASSIGN.search(files.get(path, "")):
            return mod.module, m.group(1)
    return None


def _ref_name(schema: dict[str, Any] | None) -> str | None:
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref") or (schema.get("items") or {}).get("$ref")
    return str(ref).rsplit("/", 1)[-1] if ref else None


def routes_from_openapi(spec: dict[str, Any], known: list[Route] | None = None) -> list[Route]:
    """OpenAPI -> routes; file / handler are taken from the AST route with the same handler name when present."""
    by_fn: dict[str, Route] = {}
    for r in known or []:
        by_fn.setdefault(r.function, r)
    out = []
    for path, ops in sorted((spec.get("paths") or {}).items()):
        for method, op in sorted(ops.items()):
            if method not in METHODS or not isinstance(op, dict):
                continue
            params = [f"{p.get('name')}: {(p.get('schema') or {}).get('type', '')} ({p.get('in')})".replace(": ()", "")
                      for p in op.get("parameters", []) if isinstance(p, dict)]
            body = _ref_name(((op.get("requestBody") or {}).get("content") or {}).get("application/json",
                                                                                      {}).get("schema"))
            ok = (op.get("responses") or {}).get("200") or (op.get("responses") or {}).get("201") or {}
            response = _ref_name(((ok.get("content") or {}).get("application/json") or {}).get("schema"))
            op_id = str(op.get("operationId", ""))
            ast_route = next((r for fn, r in by_fn.items() if fn and op_id.startswith(fn + "_")), None)
            out.append(Route(method=method.upper(), path=path, file=ast_route.file if ast_route else "",
                             function=ast_route.function if ast_route else "", line=ast_route.line if ast_route else 0,
                             params=params, body=body, response_model=response,
                             doc=str(op.get("description") or op.get("summary") or "")[:300], source="openapi"))
    return out


async def openapi_in_sandbox(facts: Facts, files: dict[str, str], backend: Any) -> tuple[dict[str, Any] | None, str]:
    """Import the generated app in Member 8's sandbox and read its OpenAPI document. -> (spec, note)."""
    from hmap.agents.testing.sandbox import Step

    loc = app_location(facts, files)
    if loc is None:
        return None, "no FastAPI app found"
    step = Step(stage="build", name="openapi", kind="script", args=[".docgen/openapi.py", *loc], timeout=30)
    try:
        run = await backend.run({**files, ".docgen/openapi.py": OPENAPI_SCRIPT}, [step])
    except Exception as exc:          # the sandbox itself failed: AST routes only
        return None, f"sandbox failed: {type(exc).__name__}"
    res = run.get("openapi")
    if res is None or not res.ok:
        why = (res.unavailable or res.output[-300:]) if res else (run.error or "did not run")
        if res is not None and (m := re.search(r"No module named '([\w.]+)'", res.output)):
            why = f"it needs {m.group(1)}, which the {backend.name} sandbox does not have"
        return None, f"OpenAPI not read, AST routes used: {why.strip()[:200]}"
    line = next((x for x in res.output.splitlines() if x.startswith("HMAP_OPENAPI ")), "")
    try:
        return json.loads(line.removeprefix("HMAP_OPENAPI ")), f"OpenAPI read in the {backend.name} sandbox"
    except json.JSONDecodeError:
        return None, "no OpenAPI output"


def render(facts: Facts, routes: list[Route] | None = None, title: str | None = None) -> str:
    routes = facts.routes if routes is None else routes
    lines = [f"# API reference: {title or facts.repo}", ""]
    if not routes:
        return "\n".join([*lines, "This project defines no HTTP endpoints.", ""])
    src = "the app's OpenAPI document" if any(r.source == "openapi" for r in routes) else "the code (AST)"
    lines += [f"{len(routes)} endpoint(s), read from {src}.", "", "| Endpoint | Handler |", "|---|---|"]
    lines += [f"| {r.method} {r.path} | " + (f"`{r.file}::{r.function}`" if r.file and r.function else "") + " |"
              for r in routes]
    lines.append("")
    groups: dict[str, list[Route]] = {}
    for r in routes:
        segs = [s for s in r.path.split("/") if s and not s.startswith("{")]
        key = "/" + "/".join(segs[:2]) if segs and segs[0] == "api" and len(segs) > 1 else "/" + (segs[0] if segs
                                                                                                else "")
        groups.setdefault(key, []).append(r)
    for key, rs in groups.items():
        lines += [f"## `{key}`", ""]
        for r in rs:
            lines += [f"### {r.method} {r.path}", ""]
            if r.doc:
                lines += [" ".join(r.doc.split()), ""]
            if r.file and r.function:
                lines.append(f"- Handler: `{r.file}::{r.function}`")
            if r.params:
                lines.append("- Parameters: " + ", ".join(f"`{p}`" if re.fullmatch(r"[\w: |\[\]]+", p) else p
                                                           for p in r.params))
            if r.body:
                lines.append(f"- Request body: `{r.body}`")
            if r.response_model:
                lines.append(f"- Response: `{r.response_model}`")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
