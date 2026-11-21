"""Stretch items without Docker: mutants (operators, skipped places, the local run), fuzz target selection and result
parsing, JS project detection and parsers."""

import json

from hmap.agents.testing import fuzz, mutation
from hmap.agents.testing.agent import run_mutation
from hmap.agents.testing.sandbox.local import LocalBackend
from hmap.agents.testing.stages import node
from hmap.core.config import Settings
from tests.testing.conftest import seeded_files, view_of

CODE = '''def grade(score: int) -> str:
    """Docstring stays."""
    if score >= 50 and score <= 100:
        return "pass"
    return "fail"


if __name__ == "__main__":
    print(grade(1 + 2))
'''


def test_mutants_cover_the_operators_and_skip_main_blocks() -> None:
    muts = mutation.make_mutants({"g.py": CODE}, ["g.py"], limit=50)
    ops = {m.op for m in muts}
    assert {">= -> >", "<= -> <", "and -> or", "50 -> 51", "100 -> 101", "return value -> return None"} <= ops
    assert all(m.line < 8 for m in muts)                              # nothing inside `if __name__ == ...`
    assert all(compile(m.source, m.file, "exec") for m in muts)
    assert len(mutation.make_mutants({"g.py": CODE}, ["g.py"], limit=3)) == 3
    assert mutation.parse("noise", muts).error


async def test_mutation_score_of_the_seeded_tests_locally(settings: Settings) -> None:
    st = settings.model_copy(update={"testing_mutants": 8})
    res = await run_mutation(view_of(seeded_files("good")), LocalBackend(st), st)
    assert res.error is None and res.total == 8 and res.killed >= 6, res.as_dict()
    assert all({"file", "line", "op"} <= set(s) for s in res.survived)


def test_fuzz_targets_are_simple_typed_functions_without_side_effects() -> None:
    src = ("def parse(text: str) -> list[str]:\n    return text.split()\n"
           "def add(a: int, b: int) -> int:\n    return a + b\n"
           "def serve_forever(port: int) -> None:\n    pass\n"
           "def untyped(x):\n    return x\n"
           "def opt(a: str, b: int = 1) -> str:\n    return a\n"
           "def _private(a: str) -> str:\n    return a\n"
           "def nums(v: list[int]) -> int:\n    return len(v)\n")
    tg = fuzz.targets({"m.py": src}, ["m.py"])
    assert [t["func"] for t in tg] == ["parse", "add", "nums"]
    out = ('HMAP_FUZZ ' + json.dumps([
        {"module": "m", "func": "parse", "finding": None},
        {"module": "m", "func": "add", "finding": {"exception": "TimeoutError", "message": "slow", "example":
                                                   "add(a=0, b=0)", "file": "m.py", "line": 4}}]))
    summary, found = fuzz.parse(out, tg)
    assert summary["findings"] == 1 and found[0].category == "TIMEOUT" and found[0].fuzz
    assert found[0].test == "fuzz::m.add" and "hangs" in found[0].message


def test_js_detection_and_parsers() -> None:
    assert node.is_js_project({"package.json": "{}", "a.js": ""})
    assert node.is_js_project({"a.ts": ""}) and not node.is_js_project({"a.js": "", "b.py": ""})
    report = json.dumps([{"filePath": "/work/a.js", "messages": [
        {"ruleId": "no-unused-vars", "severity": 2, "message": "'x' is unused", "line": 3},
        {"ruleId": None, "fatal": True, "severity": 2, "message": "Parsing error: Unexpected token", "line": 5}]}])
    lint, syntax = node.parse_eslint(report)
    assert (lint.category, lint.file, lint.line) == ("LINT", "a.js", 3) and syntax.category == "SYNTAX"
    syn, typ = node.parse_tsc("u.ts(4,14): error TS2322: Type 'string' is not assignable to type 'number'.\n"
                              "u.ts(1,1): error TS1005: ';' expected.\n")
    assert [f.category for f in syn] == ["SYNTAX"] and [f.line for f in typ] == [4]
    found = node.scan_js("x.js", "el.innerHTML = name;\n// eval(x) in a comment\nexec(`ls ${dir}`)\nfn(eval(s))\n")
    assert sorted(f.line for f in found) == [1, 3, 4]


async def test_dependency_audit_with_a_fake_osv_and_the_cache(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from hmap.agents.testing import deps
    files = {"requirements.txt": "# deps\nrequests==2.19.0\nflask>=2\n-r other.txt\n",
             "pyproject.toml": '[project]\nname = "x"\ndependencies = ["pyyaml==5.3", "click"]\n',
             "package.json": '{"dependencies": {"lodash": "4.17.15", "express": "^4"}}'}
    found, unpinned = deps.find(files)
    assert sorted(f"{d.name}=={d.version}@{d.file}:{d.line}" for d in found) == [
        "lodash==4.17.15@package.json:1", "pyyaml==5.3@pyproject.toml:3", "requests==2.19.0@requirements.txt:2"]
    assert len(unpinned) == 3
    calls = []

    async def fake(queries):  # type: ignore[no-untyped-def]
        calls.append(queries)
        return [[{"id": "GHSA-1", "summary": "leak", "fixed": ["2.20.0", "2.32.4"]}] if q["package"]["name"] ==
                "requests" else [] for q in queries]
    cache = tmp_path / "osv.json"
    res, fails = await deps.audit(files, "auto", query=fake, cache_path=cache)
    assert res.source == "osv" and len(calls) == 1 and len(res.audited) == 3
    assert [(f.file, f.line, f.category) for f in fails] == [("requirements.txt", 2, "SECURITY")]
    assert fails[0].hint == "pin requests to 2.32.4 or newer" and "GHSA-1" in fails[0].message
    again, fails2 = await deps.audit(files, "offline", cache_path=cache)          # the cache answers, no query
    assert again.source == "cache" and len(fails2) == 1 and len(calls) == 1

    async def down(queries):  # type: ignore[no-untyped-def]
        raise OSError("no network")
    none, nothing = await deps.audit(files, "auto", query=down, cache_path=tmp_path / "empty.json")
    assert nothing == [] and "not reachable" in none.note
    off, _ = await deps.audit(files, "off", cache_path=cache)
    assert off.note == "dependency audit off"


def test_runtime_and_image_reach_docker_run() -> None:
    from hmap.agents.testing.sandbox.docker import docker_args
    base = Settings.from_env({})
    args = docker_args(base, "n", [], None)
    assert "--runtime" not in args and args[-3:-1] == ["python3", "/opt/hmap/stages.py"] and base.testing_image in args
    gv = docker_args(base.model_copy(update={"testing_runtime": "runsc"}), "n", [], "hmap-sandbox-node:1")
    i = gv.index("--runtime")
    assert gv[i + 1] == "runsc" and "hmap-sandbox-node:1" in gv and "--network" in gv and "--read-only" in gv


def test_limits_are_layered_differently_under_gvisor() -> None:
    import base64

    from hmap.agents.testing.sandbox.docker import docker_args

    def plan_limits(args: list[str]) -> dict[str, int]:
        return dict(json.loads(base64.b64decode(args[-1]))["limits"])

    base = Settings.from_env({})
    runc = docker_args(base, "n", [], None)
    assert runc[runc.index("--memory") + 1] == "256m" and runc[runc.index("--pids-limit") + 1] == "64"
    assert plan_limits(runc) == {"nproc": 100, "as_mb": 0}            # the cgroup stops the program itself
    gv_settings = base.model_copy(update={"testing_runtime": "runsc"})
    gv = docker_args(gv_settings, "n", [], None)
    assert gv[gv.index("--memory") + 1] == "1280m" and gv[gv.index("--pids-limit") + 1] == "512"
    assert plan_limits(gv) == {"nproc": 100, "as_mb": 768}            # setrlimit inside stops it first
    node = docker_args(gv_settings, "n", [], "hmap-sandbox-node:1")
    assert plan_limits(node)["as_mb"] == 0                            # V8 reserves a huge address space
