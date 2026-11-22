"""Data of the documentation agent (Sprint 9, plan D3, D11): the facts a repository really contains, the claims a
document makes, and the trace of one run. Everything here is an artifact payload (JSON), sorted so prompts built
from it are the same on every run (replay, plan T6).

Artifact ids (all keyed by the task id; one project head ``dh-<project>`` = the latest bundle):

    db-  doc-bundle (the DocBundle contract)     drd- doc-readme        dap- doc-api         dar- doc-architecture
    dsu- doc-summaries (JSON)                     drp- doc-report        dfa- docgen-facts    dac- doc-accuracy
    dtr- docgen-trace
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

BUNDLE_TYPE = "doc-bundle"
README_TYPE = "doc-readme"
API_TYPE = "doc-api"
ARCH_TYPE = "doc-architecture"
SUMMARIES_TYPE = "doc-summaries"
REPORT_TYPE = "doc-report"
FACTS_TYPE = "docgen-facts"
ACCURACY_TYPE = "doc-accuracy"
TRACE_TYPE = "docgen-trace"
DOCSTRINGS_TYPE = "doc-docstrings"            # stretch: a patch adding docstrings (offered, never applied)

DOC_FILES: dict[str, tuple[str, str]] = {          # name in the UI / API -> (artifact type, id prefix)
    "readme": (README_TYPE, "drd"), "api": (API_TYPE, "dap"), "architecture": (ARCH_TYPE, "dar"),
    "summaries": (SUMMARIES_TYPE, "dsu"), "report": (REPORT_TYPE, "drp"),
}


def bundle_id(task_id: str) -> str:
    return f"db-{task_id}"


def doc_id(name: str, task_id: str) -> str:
    return f"{DOC_FILES[name][1]}-{task_id}"


def facts_id(task_id: str) -> str:
    return f"dfa-{task_id}"


def accuracy_id(task_id: str) -> str:
    return f"dac-{task_id}"


def trace_id(task_id: str) -> str:
    return f"dtr-{task_id}"


def docstrings_id(task_id: str) -> str:
    return f"dds-{task_id}"


def head_id(project_id: str) -> str:
    return f"dh-{project_id}"


# ------------------------------------------------------------------------------------------------- facts (9.1)


class Symbol(BaseModel):
    name: str
    kind: Literal["function", "class", "method"]
    line: int = 0
    signature: str = ""
    doc: str = ""                       # the whole docstring (first 600 characters)
    public: bool = True
    parent: str | None = None           # class of a method


class ModuleFacts(BaseModel):
    path: str
    module: str                         # dotted name ("hmap.core.config", "server")
    doc: str = ""
    lines: int = 0
    functions: list[str] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)        # top-level names of everything imported
    imported_names: list[str] = Field(default_factory=list) # names bound by imports (FastAPI, Path, ...)
    constants: list[str] = Field(default_factory=list)      # module-level UPPER_CASE names
    local_imports: list[str] = Field(default_factory=list)  # paths of the repository's own modules it imports
    symbols: list[Symbol] = Field(default_factory=list)
    main: bool = False
    error: str | None = None


class Route(BaseModel):
    method: str
    path: str
    file: str
    function: str = ""
    line: int = 0
    params: list[str] = Field(default_factory=list)          # "todo_id: int", "item: TodoIn"
    body: str | None = None                                   # a request model defined in the repository
    response_model: str | None = None
    doc: str = ""
    source: Literal["ast", "openapi"] = "ast"


class Facts(BaseModel):
    """What the repository contains. The only thing generated documentation may claim (plan D3, D7)."""

    repo: str
    language: str = "python"
    files: list[str] = Field(default_factory=list)
    modules: dict[str, ModuleFacts] = Field(default_factory=dict)
    dependencies: dict[str, str] = Field(default_factory=dict)       # name -> version spec ("" = unpinned)
    extras: list[str] = Field(default_factory=list)
    python_requires: str | None = None
    scripts: dict[str, str] = Field(default_factory=dict)            # [project.scripts] / package.json scripts
    routes: list[Route] = Field(default_factory=list)
    cli: dict[str, dict[str, list[str] | None]] = Field(default_factory=dict)   # file -> flag -> choices
    cli_required: dict[str, list[str]] = Field(default_factory=dict)             # file -> required flags
    subcommands: list[str] = Field(default_factory=list)                         # files with argparse sub-commands
    env: dict[str, str | None] = Field(default_factory=dict)          # name -> default (as text) or None
    ports: list[int] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    test_functions: int = 0
    entrypoints: list[str] = Field(default_factory=list)
    file_literals: list[str] = Field(default_factory=list)
    make_targets: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)                 # docker compose services
    technologies: list[str] = Field(default_factory=list)             # extra evidence: "docker", "node", ...
    ignored: list[str] = Field(default_factory=list)                  # .gitignore patterns (made at run time)
    notes: list[str] = Field(default_factory=list)

    def symbol_names(self) -> set[str]:
        return {s.name for m in self.modules.values() for s in m.symbols}

    def public_symbols(self) -> list[tuple[str, Symbol]]:
        return [(m.path, s) for m in self.modules.values() for s in m.symbols
                if s.public and not _is_test(m.path)]

    def code_modules(self) -> list[ModuleFacts]:
        return [m for p, m in sorted(self.modules.items()) if not _is_test(p)]


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py" or \
        "/tests/" in f"/{path}" or path.startswith("tests/")


is_test_path = _is_test


# ------------------------------------------------------------------------------------------------ claims (9.6)

ClaimKind = Literal["TECH", "ENDPOINT", "ENV", "PATH", "SYMBOL", "FLAG", "COMMAND", "PORT", "VERSION", "BEHAVIOUR",
                    "CITATION"]
Verdict = Literal["grounded", "ungrounded", "unverified", "unchecked"]


class Claim(BaseModel):
    kind: ClaimKind
    text: str                         # the claimed thing ("Redis", "GET /todos", "port 8000")
    verdict: Verdict
    why: str
    doc: str = ""                     # which document ("readme")
    sentence: str = ""                # the sentence it came from (for the UI highlight)
    line: int = 0                     # 1-based line in the document
    by: Literal["rule", "model"] = "rule"
    evidence: str = ""

    @property
    def grounded(self) -> bool:
        return self.verdict == "grounded"


class ExampleResult(BaseModel):
    doc: str
    line: int
    language: str
    code: str
    action: Literal["run", "check", "skip"]
    ok: bool | None = None            # None = not run
    why: str = ""
    output: str = ""
    backend: str = ""


class Accuracy(BaseModel):
    """The full claim table (artifact ``doc-accuracy``); the bundle carries its short form (``AccuracyReport``)."""

    grounded_pct: float = 100.0
    checked: int = 0
    grounded: int = 0
    ungrounded: int = 0
    unverified: int = 0
    claims: list[Claim] = Field(default_factory=list)
    removed: list[Claim] = Field(default_factory=list)        # dropped by the final gate (plan D9)
    examples: list[ExampleResult] = Field(default_factory=list)
    coverage_pct: float | None = None                         # public symbols documented / public symbols
    by_doc: dict[str, dict[str, int]] = Field(default_factory=dict)

    def ungrounded_lines(self) -> list[str]:
        return [f"[{c.doc}] {c.sentence or c.text} — {c.why}"[:500] for c in [*self.claims, *self.removed]
                if c.verdict == "ungrounded"]


# ------------------------------------------------------------------------------------------------------ trace


class DocgenTrace(BaseModel):
    task_id: str
    project_id: str
    execution_id: str = ""
    capability: str = "docs.generate"
    status: Literal["running", "done"] = "running"
    mode: Literal["software", "document", "none"] = "none"
    step: str = ""                                 # plan phase: design / implement / document / update
    source: str = ""                               # where the code / research came from
    workspace_ref: Any = None
    files: int = 0
    documents: list[str] = Field(default_factory=list)
    rounds: int = 0
    stop_reason: str | None = None
    scores: list[float] = Field(default_factory=list)
    model_calls: int = 0
    tokens: int = 0
    degraded: bool = False                          # no model: facts-only docs (plan D14)
    citations_removed: list[str] = Field(default_factory=list)
    injected_lines: list[str] = Field(default_factory=list)   # AI-directed lines found in repository files (D15)
    coverage: list[dict[str, Any]] = Field(default_factory=list)   # requirement -> section (report, D10)
    changed_sections: list[str] = Field(default_factory=list)      # docs.update
    fact_hashes: dict[str, str] = Field(default_factory=dict)       # document -> hash of the facts it uses
    changelog: list[str] = Field(default_factory=list)              # docs.update: what changed in the code
    docstring_patch: bool = False                                    # a dds- patch was written
    previous_bundle: str | None = None
    seconds: float = 0.0
    notes: list[str] = Field(default_factory=list)
