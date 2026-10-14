"""Reflexion (Sprint 4 item 4.5, plan D6): a short verbal note after each failed attempt — what failed and what to
change — injected into the next revision, plus a **strategy change** when the same kind of problem survives a fix.

Strategy ladder (per loop): ``targeted`` (patch only the flagged parts) -> ``full`` (the same category of major
problem survived a targeted fix: rewrite / replan the whole thing) -> ``widen`` (it survived a full rewrite too: look
at the wider input). Notes are remembered per project and task signature (``reflection-memory`` artifact, deleted
with the project): the next run of a similar task starts from them, and a category that a targeted fix could not
solve last time starts at ``full`` straight away. Members 7 and 8 can use :class:`ReflectionMemory` without a
``Refiner`` (their debug and code <-> test loops).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from hmap.agents.refine.core import SEVERITY_RANK, Attempt, RefineContext, Strategy, digest
from hmap.core.errors import Cancelled
from hmap.core.llm.base import Message
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine.reflexion")

ARTIFACT_TYPE = "reflection-memory"
MAX_NOTES = 10
LADDER: tuple[Strategy, ...] = ("targeted", "full", "widen")


def failing_categories(attempt: Attempt, at_least: str = "major") -> set[str]:
    rank = SEVERITY_RANK[at_least]
    return {i.category for i in attempt.critique.issues if SEVERITY_RANK[i.severity] >= rank}


class NoteAnswer(BaseModel):
    what_failed: str = Field(description="one sentence: what is still wrong and why the last attempt did not fix it")
    change: str = Field(description="one sentence: what to do differently next time")

    @field_validator("what_failed", "change", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return "" if value is None else value


NOTE_PROMPT = """You help an AI agent learn from an attempt that a reviewer did not accept. Given the issues the
reviewer found and what the agent changed last time (if anything), write two short sentences: what_failed (what is
wrong; if a change was made, why it did not fix it) and change (what to do in the next attempt). Be concrete; no
apologies; do not say "still" about a first attempt."""


class MemoryStore(Protocol):
    async def load(self, key: str) -> list[dict[str, Any]]: ...

    async def save(self, key: str, notes: list[dict[str, Any]]) -> None: ...


@dataclass
class InMemoryStore:
    data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def load(self, key: str) -> list[dict[str, Any]]:
        return list(self.data.get(key, []))

    async def save(self, key: str, notes: list[dict[str, Any]]) -> None:
        self.data[key] = list(notes)


class ArtifactMemoryStore:
    """Notes as a versioned ``reflection-memory`` artifact of the project (plan D6: no migration; private to the
    project and erased with it)."""

    def __init__(self, artifacts: Any, project_id: str, created_by: str = "refine") -> None:
        self.artifacts, self.project_id, self.created_by = artifacts, project_id, created_by

    @staticmethod
    def artifact_id(key: str) -> str:
        return "reflections-" + digest(key)[:16]

    async def load(self, key: str) -> list[dict[str, Any]]:
        ref = await self.artifacts.latest(self.artifact_id(key), project_id=self.project_id)
        if ref is None:
            return []
        try:
            data = json.loads(await self.artifacts.get(ref, project_id=self.project_id))
        except Exception:
            return []
        notes = data.get("notes") if isinstance(data, dict) else None
        return [n for n in notes or [] if isinstance(n, dict)]

    async def save(self, key: str, notes: list[dict[str, Any]]) -> None:
        body = json.dumps({"key": key, "notes": notes[-MAX_NOTES:]}, indent=1).encode()
        await self.artifacts.put(body, project_id=self.project_id, artifact_type=ARTIFACT_TYPE,
                                 media_type="application/json", created_by=self.created_by,
                                 artifact_id=self.artifact_id(key))


class ReflectionMemory:
    """Per-loop Reflexion state + the project's remembered notes for ``key`` (e.g. ``"document.extract:software"``)."""

    def __init__(self, key: str, store: MemoryStore | None = None, *, use_llm: bool = True, role: str = "fast",
                 at_least: str = "major") -> None:
        self.key = key
        self.store = store or InMemoryStore()
        self.use_llm = use_llm
        self.role = role
        self.at_least = at_least
        self.past: list[dict[str, Any]] = []
        self.new: list[dict[str, Any]] = []
        self.loaded = False

    async def load(self) -> "ReflectionMemory":
        try:
            self.past = await self.store.load(self.key)
        except Exception as exc:
            log.info("reflection memory not loaded", error=type(exc).__name__)
            self.past = []
        self.loaded = True
        return self

    def remembered(self) -> list[str]:
        """Notes from earlier runs of similar tasks (shown to the reviser before its first attempt)."""
        return [str(n.get("note")) for n in self.past[-3:] if n.get("note")]

    def start_strategy(self, categories: set[str]) -> Strategy:
        """A category that a targeted fix could not solve in an earlier run starts at ``full``."""
        for n in reversed(self.past):
            if n.get("outcome") == "failed" and n.get("strategy") == "targeted" and \
                    set(n.get("categories") or []) & categories:
                return "full"
        return "targeted"

    def choose_strategy(self, history: Sequence[Attempt]) -> Strategy:
        """Strategy for the next revision. Repeated failure in the same category -> one rung up the ladder."""
        latest = history[-1]
        failing = failing_categories(latest, self.at_least)
        if len(history) == 1:
            return self.start_strategy(failing)
        previous = history[-2]
        current = (latest.strategy or "targeted") if latest.strategy in LADDER else "targeted"
        repeated = failing & failing_categories(previous, self.at_least)
        if repeated:
            return LADDER[min(LADDER.index(current) + 1, len(LADDER) - 1)]
        return current

    async def reflect(self, history: Sequence[Attempt], ctx: RefineContext, next_strategy: Strategy) -> str:
        """Write the note for the latest attempt (model ``fast`` role; a rule-made note without a model)."""
        latest = history[-1]
        failing = sorted(failing_categories(latest, self.at_least))
        counts = latest.issues_by_category()
        what = ", ".join(f"{c} x{counts[c]}" for c in sorted(counts)) or "no issues"
        rule_note = (f"Attempt {latest.index} scored {latest.score:.2f} with {what}"
                     + (f" after a {latest.strategy} revision" if latest.strategy else "")
                     + (f"; next: {next_strategy}" + (" (the same problems survived the last fix)"
                                                       if next_strategy != (latest.strategy or "targeted") else "")))
        note = rule_note
        if self.use_llm and ctx.has_llm and latest.critique.issues:
            issues = "\n".join(f"- [{i.severity} {i.category}] {i.description}" for i in latest.critique.issues[:8])
            changed = "; ".join(latest.revision_notes[:3]) or "nothing: this was the first attempt"
            msgs = [Message(role="system", content=NOTE_PROMPT),
                    Message(role="user", content=f"Issues still found:\n{issues}\n\nLast change: {changed}\n\n"
                                                 f"Next strategy: {next_strategy}")]
            try:
                ans = await ctx.generate(self.role, msgs, schema=NoteAnswer, max_tokens=300)  # type: ignore[arg-type]
                if ans.what_failed.strip() or ans.change.strip():
                    note = f"{ans.what_failed.strip()} {ans.change.strip()}".strip()
            except Cancelled:
                raise
            except Exception as exc:
                log.info("reflection note by rules (model failed)", error=type(exc).__name__)
        self.new.append({"at": datetime.now(UTC).isoformat(), "iteration": latest.index, "note": note[:600],
                         "categories": failing, "strategy": latest.strategy or "targeted",
                         "next_strategy": next_strategy, "outcome": "failed"})
        return note

    async def finish(self, history: Sequence[Attempt], best: int) -> None:
        """Mark how the loop ended and persist the notes (fixed categories are recorded as such)."""
        if not history:
            return
        remaining = failing_categories(history[best], self.at_least)
        for n in self.new:
            n["outcome"] = "failed" if set(n["categories"]) & remaining else "fixed"
        if not self.new:
            return
        try:
            await self.store.save(self.key, [*self.past, *self.new][-MAX_NOTES:])
        except Exception as exc:
            log.info("reflection memory not saved", error=type(exc).__name__)
