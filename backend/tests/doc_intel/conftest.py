"""Shared helpers: the gold documents (``samples/doc_intel/gold``) as pipeline inputs."""

import json
from pathlib import Path
from typing import Any

import pytest

from hmap.agents.doc_intel.loaders import InputDocument
from hmap.core.config import REPO_ROOT

GOLD = REPO_ROOT / "samples" / "doc_intel" / "gold"


def gold_case(case_id: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((GOLD / "expected" / f"{case_id}.json").read_text())
    return data


def gold_doc(rel: str, doc_id: str = "doc-1", folder: str | None = None) -> InputDocument:
    path: Path = GOLD / "docs" / rel
    media = {".pdf": "application/pdf", ".png": "image/png", ".txt": "text/plain", ".md": "text/markdown",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[path.suffix]
    return InputDocument(doc_id=doc_id, name=path.name, data=path.read_bytes(), media_type=media, folder=folder)


@pytest.fixture
def tcp_chat() -> InputDocument:
    return gold_doc("g01_tcp_chat/tcp_chat_assignment.pdf")
