"""The stages of a test run (Sprint 8 items 8.2-8.6, plan D5), cheapest first:

``static`` (ruff, mypy) → ``build`` (compile, import) → ``unit`` (pytest, coverage) → ``integration`` (multi-process
tests, own time limit) → ``security`` (bandit + built-in rules + secret patterns) → ``execution`` (the entry point
with a sample input, only when the task names one).

Each stage module has ``steps(view)`` (what to run in the sandbox) and ``evaluate(view, run)`` (stage status +
failures from the results). :class:`View` is what the stages know about the workspace.
"""

from dataclasses import dataclass, field

from hmap.agents.coding.tools.checks import module_name


def is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def is_integration_test(rel: str, text: str) -> bool:
    return is_test_file(rel) and ("integration" in rel.lower() or "pytest.mark.integration" in text)


@dataclass
class View:
    files: dict[str, str]
    backend: str = "local"
    stage_timeout: float = 60.0
    entrypoint: list[str] = field(default_factory=list)     # ["main.py", "--flag"] (plan D5 execution)
    sample_input: str | None = None
    long_running: bool = False                               # execution: still running at the limit = fine
    deselect: list[str] = field(default_factory=list)         # generated tests dropped by the sanity gate
    coverage: bool = True
    language: str = "python"                                  # "python" | "js" (stretch: JS/TS projects)
    image: str | None = None                                  # sandbox image for this language (Docker)

    @property
    def names(self) -> set[str]:
        return set(self.files)

    @property
    def py_files(self) -> list[str]:
        return sorted(f for f in self.files if f.endswith(".py"))

    @property
    def code_files(self) -> list[str]:
        return [f for f in self.py_files if not is_test_file(f) and f.rsplit("/", 1)[-1] != "conftest.py"]

    @property
    def integration_tests(self) -> list[str]:
        return [f for f in self.py_files if is_integration_test(f, self.files[f])]

    @property
    def unit_tests(self) -> list[str]:
        integ = set(self.integration_tests)
        return [f for f in self.py_files if is_test_file(f) and f not in integ]

    @property
    def modules(self) -> list[str]:
        return sorted({m for f in self.code_files if (m := module_name(f))})

    @property
    def has_mypy_config(self) -> bool:
        if "mypy.ini" in self.files or ".mypy.ini" in self.files:
            return True
        return "[tool.mypy]" in self.files.get("pyproject.toml", "") or "[mypy]" in self.files.get("setup.cfg", "")
