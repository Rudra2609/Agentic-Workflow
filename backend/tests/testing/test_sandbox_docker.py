"""Item 8.1 abuse tests (spec: fork bomb, infinite loop, big output, network attempt, write outside) through the real
Docker sandbox, plus the seeded suite with coverage. Needs Docker and ``make sandbox-image``; skipped otherwise.
``HMAP_TESTING_RUNTIME=runsc`` runs all of it under gVisor."""

import asyncio
import os
from pathlib import Path

import pytest

from hmap.agents.testing.pipeline import run_pipeline
from hmap.agents.testing.sandbox import Step
from hmap.agents.testing.sandbox.docker import DockerBackend, docker_ready, reap
from hmap.core.config import Settings
from tests.testing.conftest import LABELS, SAMPLES, seeded_files, view_of

pytestmark = pytest.mark.integration
ABUSE = SAMPLES / "sandbox" / "abuse"
IMAGE = "hmap-sandbox-py:1"


@pytest.fixture(scope="module")
def ready() -> None:
    if not asyncio.run(docker_ready(IMAGE)):
        pytest.skip("Docker is not running or the sandbox image is missing (make sandbox-image)")


@pytest.fixture
def backend(ready: None) -> DockerBackend:
    runtime = os.environ.get("HMAP_TESTING_RUNTIME")     # e.g. runsc: the same attacks under gVisor
    return DockerBackend(Settings.from_env({"HMAP_LLM_MODE": "fake", "HMAP_TESTING_IMAGE": IMAGE,
                                            **({"HMAP_TESTING_RUNTIME": runtime} if runtime else {})}))


async def attack(backend: DockerBackend, case: str, timeout: float = 20.0, extra: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    files = {"main.py": (ABUSE / case / "main.py").read_text(encoding="utf-8"), **(extra or {})}
    run = await backend.run(files, [Step(stage="execution", name="x", kind="script", args=["main.py"],
                                         timeout=timeout)])
    assert run.error is None, run.error
    res = run.get("x")
    assert res is not None
    return res


async def test_a_normal_program_runs(backend: DockerBackend) -> None:
    res = await attack(backend, "ok")
    assert res.exit_code == 0 and "hello from the sandbox" in res.output


async def test_no_network(backend: DockerBackend) -> None:
    assert "NETWORK_BLOCKED" in (await attack(backend, "network")).output


async def test_writes_only_inside_the_workspace(backend: DockerBackend) -> None:
    assert "WRITES_CONFINED" in (await attack(backend, "write_outside")).output


async def test_not_root(backend: DockerBackend) -> None:
    assert "NOT_ROOT" in (await attack(backend, "not_root")).output


async def test_fork_bomb_is_stopped(backend: DockerBackend) -> None:
    res = await attack(backend, "fork_bomb", timeout=30)
    assert "FORK_LIMITED" in res.output and not res.timed_out


async def test_endless_loop_is_killed(backend: DockerBackend) -> None:
    res = await attack(backend, "infinite_loop", timeout=4)
    assert res.timed_out and res.seconds < 15


async def test_memory_hog_is_stopped(backend: DockerBackend) -> None:
    res = await attack(backend, "memory_hog", timeout=30)
    assert not res.timed_out and res.exit_code not in (0, None)


async def test_output_flood_is_capped(backend: DockerBackend) -> None:
    res = await attack(backend, "big_output", timeout=60)
    assert "[output cut]" in res.output and len(res.output) < 20_000


async def test_no_keys_no_docker_socket_no_project_files(backend: DockerBackend) -> None:
    probe = ("import os, pathlib\n"
             "print('ENV', sorted(k for k in os.environ if 'API_KEY' in k or 'TOKEN' in k\n"
             "                    or k.startswith(('HMAP', 'GROQ', 'GEMINI'))))\n"
             "print('SOCK', pathlib.Path('/var/run/docker.sock').exists())\n"
             "print('ENVFILE', any(pathlib.Path(p).exists() for p in ('/work/.env', '/.env')))\n")
    run = await backend.run({"probe.py": probe}, [Step(stage="execution", name="p", kind="script",
                                                       args=["probe.py"], timeout=10)])
    out = run.get("p").output  # type: ignore[union-attr]
    assert "ENV []" in out and "SOCK False" in out and "ENVFILE False" in out


async def test_cancel_kills_the_container(backend: DockerBackend) -> None:
    stop = asyncio.Event()
    files = {"main.py": (ABUSE / "infinite_loop" / "main.py").read_text(encoding="utf-8")}
    task = asyncio.create_task(backend.run(files, [Step(stage="execution", name="x", kind="script",
                                                        args=["main.py"], timeout=60)], cancelled=stop))
    await asyncio.sleep(2)
    stop.set()
    from hmap.core.errors import Cancelled
    with pytest.raises(Cancelled):
        await asyncio.wait_for(task, timeout=40)
    assert await reap() == 0          # nothing left behind


@pytest.mark.parametrize("variant", ["good", *(r["variant"] for r in LABELS)])
async def test_seeded_suite_in_docker(variant: str, backend: DockerBackend) -> None:
    expected = "PASS" if variant == "good" else next(r["category"] for r in LABELS if r["variant"] == variant)
    r = await run_pipeline(view_of(seeded_files(variant), backend="docker"), backend, flaky_check=False)
    counted = [f for f in r.failures if f.category != "LINT" and not f.flaky]
    got = counted[0].category if counted else ("LINT" if r.failures else "PASS")
    assert got == expected, [f.short() for f in r.failures]
    if variant == "good":
        assert r.coverage is not None and r.coverage > 90


def test_abuse_cases_exist() -> None:
    assert sorted(p.name for p in ABUSE.iterdir() if p.is_dir()) == sorted(
        ["ok", "network", "write_outside", "not_root", "fork_bomb", "infinite_loop", "memory_hog", "big_output"])
    assert all((ABUSE / c / "main.py").is_file() for c in ("ok", "network")) and Path(ABUSE).is_dir()


# ---------------------------------------------------------------------------------------- stretch items in Docker
JS_GOOD = {"package.json": '{"name": "x", "type": "module"}',
           "sum.js": "export function sum(a, b) {\n  return a + b;\n}\n",
           "sum.test.js": ("import { test } from 'node:test';\nimport assert from 'node:assert/strict';\n"
                           "import { sum } from './sum.js';\n\n"
                           "test('adds', () => {\n  assert.equal(sum(2, 3), 5);\n});\n")}


@pytest.fixture
def node_ready(ready: None) -> None:
    if not asyncio.run(docker_ready("hmap-sandbox-node:1")):
        pytest.skip("the Node sandbox image is missing (make sandbox-image)")


@pytest.mark.parametrize(("name", "change", "expected"), [
    ("good", {}, "PASS"),
    ("wrong", {"sum.js": "export function sum(a, b) {\n  return a - b;\n}\n"}, "ASSERTION"),
    ("syntax", {"sum.js": "export function sum(a, b) {\n  return a + ;\n}\n"}, "SYNTAX"),
    ("crash", {"sum.js": "export function sum(a, b) {\n  return a.b.c + b;\n}\n"}, "CRASH"),
    ("eval", {"sum.js": "export function sum(a, b) {\n  return eval(a + '+' + b);\n}\n"}, "SECURITY"),
    ("lint", {"sum.js": "export function sum(a, b) {\n  const unused = 1;\n  return a + b;\n}\n"}, "LINT"),
])
async def test_js_projects_in_the_node_image(name: str, change: dict[str, str], expected: str,
                                             backend: DockerBackend, node_ready: None) -> None:
    view = view_of({**JS_GOOD, **change}, backend="docker", language="js", image="hmap-sandbox-node:1", timeout=30)
    r = await run_pipeline(view, backend, flaky_check=False)
    counted = [f for f in r.failures if f.category != "LINT" and not f.flaky]
    got = counted[0].category if counted else ("LINT" if r.failures else "PASS")
    assert got == expected, [f.short() for f in r.failures]
    if expected in ("ASSERTION", "SYNTAX", "CRASH", "SECURITY"):
        assert counted[0].file in ("sum.js", "sum.test.js") and counted[0].line and counted[0].hint


async def test_typescript_type_errors_and_tests(backend: DockerBackend, node_ready: None) -> None:
    files = {"util.ts": ("export function twice(n: number): number {\n  return n * 2;\n}\n"
                         "export const bad: number = 'x';\n"),
             "util.test.ts": ("import { test } from 'node:test';\nimport assert from 'node:assert/strict';\n"
                              "import { twice } from './util.ts';\n"
                              "test('twice', () => { assert.equal(twice(2), 4); });\n")}
    r = await run_pipeline(view_of(files, backend="docker", language="js", image="hmap-sandbox-node:1", timeout=30),
                           backend, flaky_check=False)
    assert r.stages["unit"].status == "passed" and r.tests == 1
    assert [(f.category, f.file, f.line) for f in r.failures] == [("LINT", "util.ts", 4)]


async def test_fuzzing_finds_crashes_and_accepts_own_errors(backend: DockerBackend) -> None:
    from hmap.agents.testing.agent import run_fuzz
    calc = ("def mean(values: list[int]) -> float:\n    return sum(values) / len(values)\n\n\n"
            "class BadInput(Exception):\n    pass\n\n\n"
            "def first(text: str) -> str:\n    if not text.split():\n        raise BadInput('empty')\n"
            "    return text.split()[0]\n")
    summary, found = await run_fuzz(view_of({"calc.py": calc}, backend="docker", timeout=30), backend)
    assert summary["targets"] == 2 and summary["findings"] == 1
    assert found[0].fuzz and "ZeroDivisionError" in found[0].message and "values=[]" in found[0].message
    assert (found[0].file, found[0].line) == ("calc.py", 2)


async def test_mutation_score_in_docker(backend: DockerBackend) -> None:
    from hmap.agents.testing.agent import run_mutation
    st = backend.settings.model_copy(update={"testing_mutants": 6})
    res = await run_mutation(view_of(seeded_files("good"), backend="docker", timeout=20), backend, st)
    assert res.error is None and res.total == 6 and res.killed >= 4
