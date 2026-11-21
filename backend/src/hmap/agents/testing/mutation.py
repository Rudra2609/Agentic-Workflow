"""Mutation testing (Sprint 8 stretch; research §2: "a better quality signal than coverage").

When the unit tests pass, plant one small fault at a time in the code under test (a mutant) and run the tests again:
a mutant the tests notice is *killed*, one they do not notice *survives* and shows a gap in the tests. Mutants are
made with ``ast`` (DeMillo et al. 1978 operators, the mutmut subset that matters for small programs):

- comparisons ``<`` ↔ ``<=``, ``>`` ↔ ``>=``, ``==`` ↔ ``!=``, ``in`` ↔ ``not in``;
- arithmetic ``+`` ↔ ``-``, ``*`` ↔ ``//``; boolean ``and`` ↔ ``or``; ``not x`` → ``x``;
- integer constants ``n`` → ``n + 1``; ``True`` ↔ ``False``; ``return <value>`` → ``return None``.

At most ``HMAP_TESTING_MUTANTS`` mutants (default 20), spread evenly over the code, chosen deterministically. They run
inside the same sandbox as everything else, with one helper script (``.hmap/mutation_runner.py``) that writes each
mutant, runs ``pytest -x`` with a per-mutant time limit, and restores the file. Off by default
(``inputs.mutation`` or ``HMAP_TESTING_MUTATION=true``); the score is a quality number, not a failure.
"""

import ast
import json
from dataclasses import dataclass, field
from typing import Any

RUNNER_PATH = ".hmap/mutation_runner.py"
MUTANTS_PATH = ".hmap/mutants.json"
PER_MUTANT_S = 10.0
RUNNER = r'''import json, os, subprocess, sys, time
with open(sys.argv[1], encoding="utf-8") as fh:
    plan = json.load(fh)
timeout = float(sys.argv[2])
tests = sys.argv[3:]
out = []
for m in plan:
    with open(m["file"], encoding="utf-8") as fh:
        original = fh.read()
    with open(m["file"], "w", encoding="utf-8") as fh:
        fh.write(m["source"])
    started = time.monotonic()
    try:
        p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "--no-header",
                            "-p", "no:randomly", *tests], capture_output=True, timeout=timeout,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        killed, how = p.returncode != 0, ("tests failed" if p.returncode != 0 else "tests passed")
    except subprocess.TimeoutExpired:
        killed, how = True, "timed out"
    finally:
        with open(m["file"], "w", encoding="utf-8") as fh:
            fh.write(original)
    out.append({"id": m["id"], "killed": killed, "how": how, "seconds": round(time.monotonic() - started, 2)})
print("HMAP_MUTATION " + json.dumps(out))
'''

_CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
             ast.In: ast.NotIn, ast.NotIn: ast.In}
_BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult}
_SYMBOL = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=", ast.In: "in",
           ast.NotIn: "not in", ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.FloorDiv: "//"}


@dataclass
class Mutant:
    id: int
    file: str
    line: int
    op: str            # e.g. "< -> <="
    source: str        # the whole mutated file


@dataclass
class MutationResult:
    total: int = 0
    killed: int = 0
    survived: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0

    @property
    def score(self) -> float | None:
        return round(self.killed / self.total, 3) if self.total else None

    def as_dict(self) -> dict[str, Any]:
        return {"total": self.total, "killed": self.killed, "score": self.score, "survived": self.survived[:30],
                "error": self.error, "seconds": self.seconds}


def _sites(tree: ast.AST) -> list[tuple[ast.AST, str, Any]]:
    """Every place a mutation operator applies: (node, description, how to apply)."""
    out: list[tuple[ast.AST, str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in _CMP_SWAP:
                    cmp_new = _CMP_SWAP[type(op)]
                    out.append((node, f"{_SYMBOL[type(op)]} -> {_SYMBOL[cmp_new]}", ("cmp", i, cmp_new)))
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN_SWAP:
            bin_new = _BIN_SWAP[type(node.op)]
            out.append((node, f"{_SYMBOL[type(node.op)]} -> {_SYMBOL[bin_new]}", ("bin", bin_new)))
        elif isinstance(node, ast.BoolOp):
            out.append((node, "and -> or" if isinstance(node.op, ast.And) else "or -> and", ("bool",)))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            out.append((node, "not x -> x", ("not",)))
        elif isinstance(node, ast.Constant) and type(node.value) is bool:
            out.append((node, f"{node.value} -> {not node.value}", ("boolconst",)))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            out.append((node, f"{node.value} -> {node.value + 1}", ("int",)))
        elif isinstance(node, ast.Return) and node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None):
            out.append((node, "return value -> return None", ("return",)))
    return out


def _apply(node: ast.AST, how: Any) -> None:
    kind = how[0]
    if kind == "cmp":
        node.ops[how[1]] = how[2]()                    # type: ignore[attr-defined]
    elif kind == "bin":
        node.op = how[1]()                             # type: ignore[attr-defined]
    elif kind == "bool":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()   # type: ignore[attr-defined]
    elif kind == "boolconst" or kind == "int":
        node.value = (not node.value) if kind == "boolconst" else node.value + 1   # type: ignore[attr-defined]
    elif kind == "return":
        node.value = ast.Constant(value=None)          # type: ignore[attr-defined]


def _skip(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """No mutants in docstrings, type annotations, ``if __name__ == "__main__"`` blocks or decorators."""
    cur: ast.AST | None = node
    while cur is not None:
        parent = parents.get(id(cur))
        if isinstance(parent, ast.If) and isinstance(parent.test, ast.Compare) and \
                isinstance(parent.test.left, ast.Name) and parent.test.left.id == "__name__":
            return True
        if isinstance(parent, ast.arg | ast.AnnAssign) and cur is getattr(parent, "annotation", None):
            return True
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and (cur is parent.returns or
                                                                          cur in parent.decorator_list):
            return True
        cur = parent
    return False


def make_mutants(files: dict[str, str], code_files: list[str], limit: int) -> list[Mutant]:
    candidates: list[tuple[str, int, int, str]] = []        # (file, site index, line, op)
    for rel in sorted(code_files):
        try:
            tree = ast.parse(files[rel])
        except SyntaxError:
            continue
        parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for i, (node, op, _how) in enumerate(_sites(tree)):
            if not _skip(node, parents):
                candidates.append((rel, i, getattr(node, "lineno", 0), op))
    if not candidates or limit <= 0:
        return []
    step = max(1, len(candidates) // limit)
    chosen = candidates[::step][:limit]
    out = []
    for n, (rel, idx, line, op) in enumerate(chosen, 1):
        tree = ast.parse(files[rel])
        node, _op, how = _sites(tree)[idx]
        _apply(node, how)
        try:
            source = ast.unparse(ast.fix_missing_locations(tree)) + "\n"
        except Exception:   # pragma: no cover - ast.unparse handles every tree we can build
            continue
        out.append(Mutant(id=n, file=rel, line=line, op=op, source=source))
    return out


def plan_files(mutants: list[Mutant]) -> dict[str, str]:
    return {RUNNER_PATH: RUNNER,
            MUTANTS_PATH: json.dumps([{"id": m.id, "file": m.file, "source": m.source} for m in mutants])}


def parse(output: str, mutants: list[Mutant]) -> MutationResult:
    line = next((ln for ln in reversed(output.splitlines()) if ln.startswith("HMAP_MUTATION ")), None)
    res = MutationResult()
    if line is None:
        res.error = "the mutation run gave no result (time limit or crash)"
        return res
    by_id = {m.id: m for m in mutants}
    for r in json.loads(line[len("HMAP_MUTATION "):]):
        m = by_id.get(r["id"])
        if m is None:
            continue
        res.total += 1
        if r["killed"]:
            res.killed += 1
        else:
            res.survived.append({"file": m.file, "line": m.line, "op": m.op})
    return res
