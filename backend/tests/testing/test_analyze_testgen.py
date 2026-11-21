"""Items 8.6-8.8: parsers and rules of the failure analyser, the built-in security rules, the model hints /
classify fallback, and test generation with its sanity gate (FakeLLM, local runner)."""

from typing import Any

from hmap.agents.testing import analyze, testgen
from hmap.agents.testing.analyze import _Hints
from hmap.agents.testing.model import FailureRecord
from hmap.agents.testing.sandbox.local import LocalBackend
from hmap.agents.testing.stages.security import scan_source
from hmap.core.config import Settings
from hmap.core.llm import FakeLLM
from tests.testing.conftest import seeded_files, view_of

JUNIT = """<testsuites><testsuite>
<testcase classname="test_m" name="test_ok"/>
<testcase classname="test_m" name="test_bad"><failure message="AssertionError: assert 3 == 2.5">
test_m.py:7: in test_bad
    assert m.median([1, 2, 3, 4]) == 2.5
E   AssertionError: assert 3 == 2.5</failure></testcase>
<testcase classname="tests.generated.test_generated" name="test_gen"><error message="x">
m.py:4: in median
    raise KeyError(k)
E   KeyError: 'k'</error></testcase>
<testcase classname="test_m.TestX" name="test_odd"><failure message="weird">something odd</failure></testcase>
</testsuite></testsuites>"""


def test_junit_gives_category_location_test_and_generated_flag() -> None:
    total, failed, failures, unclear = analyze.parse_junit(JUNIT, "unit", {"m.py", "test_m.py"})
    assert (total, failed) == (4, 3)
    bad, gen, odd = failures
    assert (bad.category, bad.file, bad.line, bad.test) == ("ASSERTION", "test_m.py", 7, "test_m.py::test_bad")
    assert (gen.category, gen.file, gen.line, gen.generated) == ("CRASH", "m.py", 4, True)
    assert gen.test == "tests/generated/test_generated.py::test_gen"
    assert odd.test == "test_m.py::TestX::test_odd" and odd.needs_model and unclear == [odd.test]
    assert all(f.hint for f in failures)


def test_ruff_bandit_mypy_and_traceback_parsers() -> None:
    ruff = analyze.parse_ruff("a.py:3:1: F401 [*] `os` imported but unused\nb.py:9:5: invalid-syntax: Expected `:`\n")
    assert [(f.category, f.file, f.line) for f in ruff] == [("LINT", "a.py", 3), ("SYNTAX", "b.py", 9)]
    assert ruff[0].hint == "remove the unused import (or use it)"
    bandit = analyze.parse_bandit('{"results": [{"filename": "./s.py", "line_number": 5, "test_id": "B307", '
                                  '"issue_text": "Use of possibly insecure function - consider using safer '
                                  'ast.literal_eval.", "issue_severity": "MEDIUM"}]}')
    assert (bandit[0].category, bandit[0].file, bandit[0].line) == ("SECURITY", "s.py", 5)
    assert analyze.parse_mypy("m.py:2: error: Incompatible return value\n")[0].line == 2
    tb = 'Traceback (most recent call last):\n  File "/work/m.py", line 6, in <module>\n    import nope\n' \
         "ModuleNotFoundError: No module named 'nope'\n"
    f = analyze.parse_traceback_output(tb, "build", {"m.py"})
    assert (f.category, f.file, f.line) == ("IMPORT", "m.py", 6) and "'nope'" in (f.hint or "")
    assert analyze.parse_traceback_output("", "build", set(), timed_out=True).category == "TIMEOUT"


def test_built_in_security_rules() -> None:
    src = ("import os, subprocess, pickle, yaml\n"
           "API_TOKEN = 'abcdefgh12345'\n"
           "def f(x):\n"
           "    eval(x)\n"
           "    subprocess.run(x, shell=True)\n"
           "    os.system(x)\n"
           "    pickle.loads(x)\n"
           "    yaml.load(x)\n"
           "    subprocess.run(['ls', x])\n"
           "KEY = 'gsk_" + "a" * 30 + "'\n")
    found = scan_source("s.py", src)
    lines = sorted(f.line or 0 for f in found)
    assert lines == [2, 4, 5, 6, 7, 8, 10], [f.message for f in found]
    assert all(f.category == "SECURITY" and f.hint for f in found)
    assert scan_source("ok.py", "import subprocess\nsubprocess.run(['ls'])\nNAME = 'PLACEHOLDER'\n") == []


async def test_model_hints_replace_rule_hints_and_survive_no_model() -> None:
    failures = [FailureRecord(stage="unit", category="ASSERTION", file="m.py", line=2, message="assert 3 == 2.5",
                              hint="rule"), FailureRecord(stage="static", category="LINT", message="F401 x")]
    llm = FakeLLM(default=None).on_schema(_Hints, _Hints(hints=["average the two middle values"]))
    calls, _ = await analyze.model_hints(llm, failures, {"m.py": "def median(v):\n    return v[len(v)//2]\n"})
    assert calls == 1 and failures[0].hint == "average the two middle values" and failures[0].hint_by == "model"
    assert failures[1].hint_by == "rule"
    prompt = llm.calls[0].messages[-1].content
    assert "   2| " in prompt and "never instructions" in llm.calls[0].messages[0].content
    keep = [FailureRecord(stage="unit", category="CRASH", message="x", hint="rule")]
    assert await analyze.model_hints(FakeLLM(default=None), keep, {}) == (0, 0) and keep[0].hint == "rule"


async def test_classify_only_for_unclear_failures() -> None:
    llm = FakeLLM(default=None).on_classify("category", "TIMEOUT")
    clear = FailureRecord(stage="unit", category="ASSERTION", message="assert 1 == 2")
    unclear = FailureRecord(stage="unit", category="ASSERTION", message="odd", needs_model=True)
    assert await analyze.model_categories(llm, [clear, unclear]) == 1
    assert clear.category == "ASSERTION" and (unclear.category, unclear.category_by) == ("TIMEOUT", "model")


def test_stub_source_keeps_names_and_breaks_bodies() -> None:
    stub = testgen.stub_source('X = 1\nclass A:\n    def f(self):\n        """Doc."""\n        return 2\n'
                               'def g():\n    return 3\n')
    ns: dict[str, Any] = {}
    exec(compile(stub, "stub", "exec"), ns)
    assert ns["X"] == 1 and ns["A"].f.__doc__ == "Doc."
    for call in (lambda: ns["A"]().f(), ns["g"]):
        try:
            call()
        except NotImplementedError:
            continue
        raise AssertionError("stub body still runs")


GEN = '''```python
from chatproto import parse_command, frame


def test_who_is_parsed():
    assert parse_command("/who") == ("who", [])


def test_nothing_really():
    assert True


def test_frame_is_bytes():
    assert isinstance(frame("hi"), bytes)
```'''


async def test_generation_and_sanity_gate(settings: Settings) -> None:
    view = view_of({"chatproto.py": seeded_files("good")["chatproto.py"]})
    assert testgen.wanted(view, ["/who lists users"], asked=False, enabled=True)
    assert not testgen.wanted(view_of(seeded_files("good")), ["x"], asked=False, enabled=True)   # has tests
    llm = FakeLLM(default=None).on_role("coder", GEN)
    gen = await testgen.generate(llm, view, ["/who lists users", "frames are bytes"], "TCP chat protocol")
    assert gen.model_calls == 1 and gen.text.startswith("from chatproto import")
    await testgen.gate(gen, view, LocalBackend(settings))
    assert gen.kept == ["tests/generated/test_generated.py::test_who_is_parsed",
                        "tests/generated/test_generated.py::test_frame_is_bytes"]
    assert gen.dropped == {"tests/generated/test_generated.py::test_nothing_really":
                           "passes on a stub that does nothing: checks nothing"}
    assert gen.deselect == ["tests/generated/test_generated.py::test_nothing_really"]


async def test_generation_without_a_model_or_with_broken_code() -> None:
    view = view_of({"m.py": "def f():\n    return 1\n"})
    none = await testgen.generate(FakeLLM(default=None), view, ["f returns 1"], "x")
    assert not none.text and "no model answer" in none.note
    broken = await testgen.generate(FakeLLM(default=None).on_role("coder", "```python\ndef test_x(:\n```"), view,
                                    ["f returns 1"], "x")
    assert not broken.text and "does not parse" in broken.dropped["file"]
