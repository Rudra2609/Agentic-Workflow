"""Flaky-test quarantine (Sprint 8 stretch, research §5).

A test that failed and then passed on the re-run (``pipeline.recheck_flaky``) is recorded per project in the
artifact ``tq-<project_id>``. From then on it still runs, but its failures are marked flaky ("quarantined"): reported,
never counted against the run and never sent to Member 7. It is released automatically after ``RELEASE_AFTER``
clean passes in a row, or by a person (``POST /api/testing/quarantine/{project}/release``).
"""

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from hmap.agents.testing.model import FailureRecord
from hmap.services.artifact.base import ArtifactStore

QUARANTINE_TYPE = "testing-quarantine"
RELEASE_AFTER = 3


def quarantine_id(project_id: str) -> str:
    return f"tq-{project_id}"


class Entry(BaseModel):
    flaky: int = 0                  # times it was seen flaky
    clean_passes: int = 0           # passes in a row since it was last flaky
    first_seen: str = ""
    last_seen: str = ""
    last_task_id: str | None = None


class Quarantine(BaseModel):
    project_id: str
    tests: dict[str, Entry] = Field(default_factory=dict)
    released: list[str] = Field(default_factory=list)   # most recent first, capped

    def active(self) -> set[str]:
        return set(self.tests)


async def load(store: ArtifactStore, project_id: str) -> Quarantine:
    ref = await store.latest(quarantine_id(project_id), project_id=project_id)
    if ref is None:
        return Quarantine(project_id=project_id)
    try:
        return Quarantine.model_validate_json(await store.get(ref, project_id=project_id))
    except ValueError:
        return Quarantine(project_id=project_id)


async def save(store: ArtifactStore, q: Quarantine, created_by: str) -> None:
    await store.put(q.model_dump_json(indent=2).encode(), project_id=q.project_id, artifact_type=QUARANTINE_TYPE,
                    media_type="application/json", created_by=created_by, artifact_id=quarantine_id(q.project_id))


def apply(q: Quarantine, failures: list[FailureRecord]) -> list[str]:
    """Mark failures of quarantined tests as flaky; returns the node ids that were quarantined in this run."""
    hit = []
    for f in failures:
        if f.test and f.test in q.tests and not f.flaky:
            f.flaky = True
            f.hint = (f"quarantined: this test was flaky before ({q.tests[f.test].flaky}x); it does not count until "
                      f"it passes {RELEASE_AFTER} times in a row")
            hit.append(f.test)
    return hit


def update(q: Quarantine, *, flaky: list[str], failed: set[str], passed: set[str], task_id: str) -> bool:
    """New flaky tests in, clean passes counted, released after ``RELEASE_AFTER``; returns True when it changed."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    changed = False
    for node in flaky:
        e = q.tests.setdefault(node, Entry(first_seen=now))
        e.flaky, e.clean_passes, e.last_seen, e.last_task_id = e.flaky + 1, 0, now, task_id
        changed = True
    for node in list(q.tests):
        if node in flaky or node in failed:
            continue
        if node in passed:
            q.tests[node].clean_passes += 1
            changed = True
            if q.tests[node].clean_passes >= RELEASE_AFTER:
                del q.tests[node]
                q.released = [node, *[r for r in q.released if r != node]][:50]
    return changed


def release(q: Quarantine, node: str) -> bool:
    if node not in q.tests:
        return False
    del q.tests[node]
    q.released = [node, *[r for r in q.released if r != node]][:50]
    return True


def as_dict(q: Quarantine) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(q.model_dump_json())
    return out
