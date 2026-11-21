"""Shared fixtures for the testing agent's tests: settings with the local runner (no Docker needed) and the
seeded-failure suite (``samples/testing/seeded_failures``)."""

import json
from pathlib import Path

import pytest

from hmap.agents.testing.stages import View
from hmap.core.config import Settings

SAMPLES = Path(__file__).resolve().parents[3] / "samples" / "testing"
SEEDED = SAMPLES / "seeded_failures"
LABELS: list[dict[str, str]] = json.loads((SEEDED / "labels.json").read_text(encoding="utf-8"))


def seeded_files(variant: str) -> dict[str, str]:
    folder = SEEDED / ("good" if variant == "good" else f"variants/{variant}")
    return {"chatproto.py": (folder / "chatproto.py").read_text(encoding="utf-8"),
            "test_chatproto.py": (SEEDED / "good" / "test_chatproto.py").read_text(encoding="utf-8")}


def view_of(files: dict[str, str], *, backend: str = "local", timeout: float = 8.0, **kw: object) -> View:
    return View(files=dict(files), backend=backend, stage_timeout=timeout, **kw)  # type: ignore[arg-type]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path / "work"), "HMAP_LLM_MODE": "fake",
                              "HMAP_TESTING_SANDBOX": "local", "HMAP_TESTING_STAGE_TIMEOUT_S": "8"})
