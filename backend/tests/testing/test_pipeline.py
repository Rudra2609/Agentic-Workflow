"""Items 8.2-8.6, 8.12: the stage pipeline on the local runner: the seeded suite (good + 15 variants) is
classified as labelled, plus integration, execution, generated-test deselection and the flaky re-check."""

import pytest

from hmap.agents.testing.model import FailureRecord
from hmap.agents.testing.pipeline import PipelineResult, normalise, recheck_flaky, run_pipeline
from hmap.agents.testing.sandbox import RunResult, Step, StepResult
from hmap.agents.testing.sandbox.local import LocalBackend
from hmap.agents.testing.stages import View
from hmap.core.config import Settings
from tests.testing.conftest import LABELS, seeded_files, view_of

CASES = [("good", "PASS"), *((row["variant"], row["category"]) for row in LABELS)]


def verdict(r: PipelineResult) -> str:
    """The category the analyser gives a seeded variant: the first counted failure, else LINT, else PASS."""
    counted = [f for f in r.failures if f.category != "LINT" and not f.flaky]
    if counted:
        return counted[0].category
    return "LINT" if r.failures else "PASS"


@pytest.mark.parametrize(("variant", "expected"), CASES, ids=[c[0] for c in CASES])
async def test_seeded_suite_is_classified_as_labelled(variant: str, expected: str, settings: Settings) -> None:
    r = await run_pipeline(view_of(seeded_files(variant)), LocalBackend(settings), flaky_check=False)
    assert verdict(r) == expected, [f.short() for f in r.failures]
    assert r.passed is (expected in ("PASS", "LINT"))
    for f in r.failures:
        assert f.hint, f.short()
        if f.category in ("SYNTAX", "IMPORT", "CRASH", "SECURITY", "LINT"):
            assert f.file == "chatproto.py" and f.line, f.short()


async def test_good_version_runs_every_stage_it_can(settings: Settings) -> None:
    r = await run_pipeline(view_of(seeded_files("good")), LocalBackend(settings))
    assert {k: s.status for k, s in r.stages.items()} == {
        "static": "passed", "build": "passed", "unit": "passed", "integration": "skipped", "security": "passed",
        "execution": "skipped"}
    assert r.tests == 8 and r.tests_failed == 0 and r.pass_ratio == 1.0
    assert "local runner" in r.stages["static"].detail


async def test_a_file_that_does_not_compile_skips_the_tests(settings: Settings) -> None:
    r = await run_pipeline(view_of(seeded_files("syntax_error")), LocalBackend(settings))
    assert r.stages["build"].status == "failed" and r.stages["unit"].status == "skipped"
    assert [f.category for f in r.failures] == ["SYNTAX"]     # ruff and py_compile: one failure, not two


TCP_SERVER = '''import socket, threading

def serve(sock):
    def handle(conn):
        with conn:
            data = conn.recv(1024)
            conn.sendall(data.upper() if UPPER else data)
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        threading.Thread(target=handle, args=(conn,), daemon=True).start()

UPPER = True
'''
TCP_TEST = '''import socket, threading
import pytest
from server import serve

@pytest.mark.integration
def test_three_clients_get_upper_case():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    threading.Thread(target=serve, args=(sock,), daemon=True).start()
    for i in range(3):
        with socket.create_connection(("127.0.0.1", port), timeout=3) as c:
            c.sendall(b"hi%d" % i)
            assert c.recv(1024) == b"HI%d" % i
    sock.close()
'''


async def test_integration_stage_runs_a_tcp_server_with_clients(settings: Settings) -> None:
    files = {"server.py": TCP_SERVER, "tests/integration/test_server.py": TCP_TEST}
    good = await run_pipeline(view_of(files), LocalBackend(settings), flaky_check=False)
    assert good.stages["integration"].status == "passed" and good.stages["integration"].tests == 1
    assert good.stages["unit"].status == "skipped"
    bad = await run_pipeline(view_of({**files, "server.py": TCP_SERVER.replace("UPPER = True", "UPPER = False")}),
                             LocalBackend(settings), flaky_check=False)
    assert bad.stages["integration"].status == "failed"
    integ = [f for f in bad.failures if f.stage == "integration"]
    assert [f.category for f in integ] == ["ASSERTION"]


async def test_execution_stage_runs_the_entry_point_with_a_sample_input(settings: Settings) -> None:
    files = {"main.py": "import sys\nprint(sum(int(x) for x in sys.argv[1:]))\n"}
    ok = await run_pipeline(view_of(files, entrypoint=["main.py", "2", "3"]), LocalBackend(settings))
    assert ok.stages["execution"].status == "passed"
    crash = await run_pipeline(view_of(files, entrypoint=["main.py", "x"]), LocalBackend(settings))
    assert crash.stages["execution"].status == "failed"
    assert crash.failures[0].category == "CRASH" and crash.failures[0].file == "main.py"
    none = await run_pipeline(view_of(files), LocalBackend(settings))
    assert none.stages["execution"].status == "skipped"


async def test_deselected_generated_tests_do_not_run(settings: Settings) -> None:
    files = {"m.py": "def f():\n    return 1\n",
             "tests/generated/test_generated.py": "from m import f\n\ndef test_a():\n    assert f() == 1\n\n"
                                                  "def test_b():\n    assert f() == 2\n"}
    r = await run_pipeline(view_of(files, deselect=["tests/generated/test_generated.py::test_b"]),
                           LocalBackend(settings), flaky_check=False)
    assert r.passed and r.tests == 1


class FlakyBackend:
    """First run: test_x fails; the re-check run: it passes."""
    name, isolation = "fake", "none"

    async def run(self, files: dict[str, str], steps: list[Step], *, cancelled: object = None,
                  image: str | None = None) -> RunResult:
        xml = '<testsuites><testsuite><testcase classname="test_m" name="test_x"/></testsuite></testsuites>'
        return RunResult(backend="fake", steps=[StepResult(name="recheck", stage="unit", exit_code=0,
                                                           files={".xml": xml})])


async def test_a_failure_that_passes_on_the_re_run_is_flaky() -> None:
    out = PipelineResult(backend="fake", failures=[FailureRecord(stage="unit", category="ASSERTION",
                                                                 test="test_m.py::test_x", message="boom")])
    await recheck_flaky(View(files={"test_m.py": ""}), FlakyBackend(), out)
    assert out.failures[0].flaky and out.flaky == ["test_m.py::test_x"]
    assert out.passed       # flaky failures are reported but do not fail the run


def test_normalise_removes_paths_timings_and_temp_names() -> None:
    text = "/work/a.py:3 failed in 0.53s tmpab12cd34 port 50123 ('127.0.0.1', 4242) 0xdeadbeef1"
    assert normalise(text) == "a.py:3 failed tmpXXXXXXXX port N ('127.0.0.1', N) 0x?"
