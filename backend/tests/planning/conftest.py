"""Shared helpers: the planning gold inputs (``samples/planning/gold/inputs``) and small requirement sets."""

import json
from typing import Any

from hmap.core.config import REPO_ROOT
from hmap.core.contracts.domain import RequirementSet

GOLD = REPO_ROOT / "samples" / "planning" / "gold"


def gold_rs(case: str) -> RequirementSet:
    return RequirementSet.model_validate_json((GOLD / "inputs" / f"{case}.requirement_set.json").read_text())


def gold_sections(case: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((GOLD / "inputs" / f"{case}.sections.json").read_text())
    return data


def req(rid: str, text: str, *, priority: str = "must", type_: str = "functional", folder: str | None = None,
        confidence: float = 0.95) -> dict[str, Any]:
    return {"id": rid, "text": text, "priority": priority, "type": type_, "confidence": confidence,
            "source_ref": {"doc_id": "doc-1", "quote": text, "folder": folder}}


def small_rs(**extra: Any) -> RequirementSet:
    data: dict[str, Any] = {
        "project_id": "P-PLAN",
        "requirements": [req("R1", "The server must accept at least 10 clients."),
                         req("R2", "Each client must choose a unique nickname."),
                         req("R3", "Clients should send private messages to a nickname.", priority="should"),
                         req("R4", "The server must not crash when a client disconnects.", type_="non_functional")],
        "constraints": [{"id": "C1", "text": "Use Python 3.11 and the standard library only.", "kind": "technology"}],
        "deliverables": [{"id": "D1", "name": "Source code ZIP", "format": "zip"},
                         {"id": "D2", "name": "README", "format": ""}],
    }
    data.update(extra)
    return RequirementSet.model_validate(data)
