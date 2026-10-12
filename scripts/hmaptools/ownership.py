"""Map changed files to owners using ownership.toml and flag edits outside a member's own paths."""

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _match(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        return path == pattern[:-3] or path.startswith(pattern[:-2])
    return fnmatch.fnmatchcase(path, pattern)


def _specificity(pattern: str) -> int:
    return len(pattern.replace("*", ""))


@dataclass
class Ownership:
    members: dict[int, list[str]]
    names: dict[int, str]
    common: list[str]
    cross_cutting: dict[int, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Ownership":
        data = tomllib.loads(path.read_text())
        members = {int(k): list(v["paths"]) for k, v in data["members"].items()}
        names = {int(k): v.get("name", "") for k, v in data["members"].items()}
        cross = {int(k): list(v) for k, v in data.get("cross_cutting", {}).items()}
        return cls(members, names, list(data.get("common", {}).get("paths", [])), cross)

    def owner(self, path: str) -> int | None:
        """Most specific matching pattern wins (frontend/src/features/doc_intel/** beats frontend/**)."""
        best: tuple[int, int] | None = None
        for member, patterns in self.members.items():
            for pat in patterns:
                if _match(path, pat) and (best is None or _specificity(pat) > best[1]):
                    best = (member, _specificity(pat))
        return best[0] if best else None

    def classify(self, member: int, path: str) -> str:
        """own | common | cross_cutting (needs Member 1 sign-off) | shared (Member 1's, needs sign-off) |
        foreign (another member's path: error) | unowned (no rule: needs a new ownership entry)."""
        if any(_match(path, p) for p in self.common):
            return "common"
        owner = self.owner(path)
        if owner == member:
            return "own"
        if any(_match(path, p) for p in self.cross_cutting.get(member, [])):
            return "cross_cutting"
        if owner is None:
            return "unowned"
        if owner == 1:
            return "shared"
        return "foreign"


@dataclass
class OwnershipReport:
    member: int
    rows: list[tuple[str, str, int | None]]

    @property
    def errors(self) -> list[tuple[str, str, int | None]]:
        return [r for r in self.rows if r[1] in ("foreign", "unowned")]

    @property
    def needs_signoff(self) -> list[tuple[str, str, int | None]]:
        return [r for r in self.rows if r[1] in ("shared", "cross_cutting")]


def check(own: Ownership, member: int, changed: list[str]) -> OwnershipReport:
    return OwnershipReport(member, [(p, own.classify(member, p), own.owner(p)) for p in changed])
