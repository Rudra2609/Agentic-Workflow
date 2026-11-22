"""Shared helpers for the documentation agent's tests: the prototype's sample repos (``samples/docgen/repos``), the
seeded false claims, workspace tarballs in memory and an agent context on the in-memory stores."""

import io
import json
import logging
import tarfile
from pathlib import Path
from typing import Any

import pytest

from hmap.agents.docgen.inspect import inspect_files, read_tree
from hmap.agents.docgen.model import Facts
from hmap.core.config import Settings
from hmap.core.contracts import TaskAssign
from hmap.core.contracts.capabilities import DOCS_GENERATE
from hmap.core.llm import FakeLLM
from hmap.core.runtime.base import AgentContext
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "samples" / "docgen"
REPOS = SAMPLES / "repos"
REPO_NAMES = ("tcp_chat", "todo_api", "csv_report")
SEEDED: list[dict[str, Any]] = json.loads((SAMPLES / "seeded.json").read_text(encoding="utf-8"))


def repo_files(name: str) -> dict[str, str]:
    return read_tree(REPOS / name)


def repo_facts(name: str) -> Facts:
    return inspect_files(repo_files(name), name)


def readme_of(name: str) -> str:
    return (REPOS / name / "README.md").read_text(encoding="utf-8")


def tar_of(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, text in sorted(files.items()):
            data = text.encode()
            info = tarfile.TarInfo(rel)
            info.size, info.mtime = len(data), 0
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def assign(**kw: Any) -> TaskAssign:
    base: dict[str, Any] = {"task_id": "T1", "execution_id": "E1", "capability": DOCS_GENERATE,
                            "objective": "Write the README and report", "acceptance_criteria": ["docs exist"],
                            "context_refs": [], "project_id": "P"}
    return TaskAssign(**(base | kw))


def ctx_for(task: TaskAssign, store: InMemoryArtifactStore, llm: Any = None) -> AgentContext:
    return AgentContext(task=task, agent_id="docgen-1", llm=llm or FakeLLM(default=None), artifacts=store,
                        context=InMemoryContextStore(), logger=logging.getLogger("t"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path / "work"), "HMAP_LLM_MODE": "fake",
                              "HMAP_TESTING_SANDBOX": "local", "HMAP_TESTING_STAGE_TIMEOUT_S": "20"})
