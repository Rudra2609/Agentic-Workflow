"""Items 7.2 (repo map), 7.8 (context budget) and 7.10 (templates)."""

import random
import shutil

import pytest
from hypothesis import given
from hypothesis import settings as hsettings
from hypothesis import strategies as st

from hmap.agents.coding import templates
from hmap.agents.coding.context_budget import Part, cut_middle, fit, tokens, window
from hmap.agents.coding.repomap import RepoMap, parse_python, symbol_lines
from hmap.agents.coding.tools import sandbox
from hmap.agents.coding.tools.checks import Checker
from hmap.agents.coding.tools.runner import Runner
from hmap.agents.coding.workspace import Workspace
from hmap.core.config import Settings
from tests.coding.conftest import BENCH

SRC = '''"""Room of connected clients."""
import socket
from framing import frame

MAX = 10


class Room:
    def join(self, conn, name: str) -> None:
        pass

    async def broadcast(self, text, sender=None):
        pass


def helper(x: int = 1) -> int:
    return x
'''


def test_parse_python_lists_symbols_signatures_and_imports() -> None:
    e = parse_python("room.py", SRC)
    assert e.doc == "Room of connected clients."
    assert e.symbols == ["MAX = …", "class Room", "  def join(self, conn, name: str) -> None",
                         "  async def broadcast(self, text, sender=None)", "def helper(x: int=1) -> int"]
    assert e.imports == ["socket", "framing"] and e.top == ["MAX", "Room", "helper"]
    assert parse_python("bad.py", "def (:\n").error == "SyntaxError line 1"
    assert symbol_lines(SRC)["Room.broadcast"] == (12, 13)


@pytest.mark.parametrize("task", sorted(p.name for p in BENCH.iterdir() if (p / "starter").is_dir()))
def test_every_benchmark_map_fits_1500_tokens(task: str, tmp_path) -> None:
    shutil.copytree(BENCH / task / "starter", tmp_path / "ws")
    rmap = RepoMap.build(Workspace(tmp_path / "ws"))
    assert tokens(rmap.render(1500)) <= 1500


def test_repo_map_is_incremental_and_cut_to_budget(ws: Workspace) -> None:
    for i in range(40):
        ws.write(f"pkg/mod{i:02d}.py", SRC.replace("Room", f"Room{i}"))
    ws.write("README.md", "# readme\n")
    first = RepoMap.build(ws)
    assert first.parsed >= 1 and len(first.entries) == 41
    ws.write("pkg/mod03.py", SRC + "\ndef extra():\n    pass\n")
    second = RepoMap.build(ws, previous=first)
    assert second.parsed == 1                                   # only the changed file is parsed again
    full = second.render(100_000, focus=["pkg/mod03.py"])
    assert "def extra()" in full and "README.md (2 lines)" in full
    small = second.render(300, focus=["pkg/mod03.py"])
    assert tokens(small) <= 300 and small.startswith("pkg/mod03.py")


def test_fit_keeps_required_parts_and_never_exceeds_the_budget() -> None:
    parts = [Part("task", "T" * 300, priority=0, required=True), Part("failure", "F" * 3000, priority=1, required=True),
             Part("file", "X" * 9000, priority=10), Part("map", "M" * 3000, priority=20)]
    kept, changed = fit(parts, 1500)
    names = [p.name for p in kept]
    assert names[:2] == ["task", "failure"] and tokens("\n\n".join(p.text for p in kept)) <= 1500
    assert any("(cut)" in c or "(dropped)" in c for c in changed)


@hsettings(max_examples=150, deadline=None)
@given(sizes=st.lists(st.integers(0, 20_000), min_size=1, max_size=8), budget=st.integers(200, 8000),
       seed=st.integers(0, 10))
def test_fit_property_never_over_budget(sizes: list[int], budget: int, seed: int) -> None:
    rnd = random.Random(seed)
    parts = [Part(f"p{i}", "x" * n, priority=rnd.randint(0, 50), required=(i == 0)) for i, n in enumerate(sizes)]
    kept, _ = fit(parts, budget)
    assert tokens("\n\n".join(p.text for p in kept)) <= budget
    assert kept and kept[0].name == "p0"                        # the required part is always there


def test_cut_middle_and_window() -> None:
    assert cut_middle("abc", 10) == "abc"
    cut = cut_middle("a" * 1000 + "b" * 1000, 200)
    assert tokens(cut) <= 200 and cut.startswith("a") and cut.endswith("b")
    text = "\n".join(f"line {i}" for i in range(1, 401))
    part, a, b = window(text, [(200, 205)], pad=10)
    assert (a, b) == (190, 215) and part.startswith("line 190")
    assert window("short\n", [(1, 1)])[1:] == (1, 2)


# --------------------------------------------------------------------------------------------------- templates


def test_four_templates_with_metadata() -> None:
    names = set(templates.all_templates())
    assert names == {"python_package", "fastapi_service", "tcp_server_client", "cli"}


@pytest.mark.parametrize(("text", "expected"), [
    ("Build a multi-client TCP chat server and client using sockets", "tcp_server_client"),
    ("REST API with endpoints to create and fetch items as JSON", "fastapi_service"),
    ("A command line tool that reads a CSV file and prints a report", "cli"),
    ("Implement an LRU cache class with get and put", "python_package"),
    ("Write an essay about the history of computing", None),
])
def test_keyword_selection(text: str, expected: str | None) -> None:
    assert templates.choose(text)[0] == expected


@pytest.mark.parametrize("name", ["python_package", "fastapi_service", "tcp_server_client", "cli"])
async def test_every_template_passes_its_own_checks_in_the_runner(name: str, ws: Workspace,
                                                                   settings: Settings) -> None:
    template = templates.all_templates()[name]
    if template.requires and not (sandbox.CODING_VENV / "bin" / "python").exists() and not settings.coding_python:
        pytest.skip(f"{name} needs {', '.join(template.requires)}: run make coding-venv")
    installed = template.install(ws)
    assert installed and "template.json" not in installed
    run = await Checker(Runner(ws, settings)).run(1)
    assert run.passed, run.failures_for_model()
    assert any(c.name == "tests" and c.status in ("passed", "skipped") for c in run.checks)
