"""Shared fixtures for the coding agent's tests: settings whose work folder is pytest's tmp folder (outside the
project), and a workspace inside it."""

from pathlib import Path

import pytest

from hmap.agents.coding.workspace import Workspace
from hmap.core.config import Settings

BENCH = Path(__file__).resolve().parents[3] / "samples" / "coding" / "tasks"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path / "work"), "HMAP_LLM_MODE": "fake"})


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir()
    return Workspace(root)


def block(path: str, search: str, replace: str) -> str:
    return f"{path}\n<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n"
