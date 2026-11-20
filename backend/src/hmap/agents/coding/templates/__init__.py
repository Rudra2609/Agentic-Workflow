"""Scaffolding templates (Sprint 7 item 7.10, plan D8): ``python_package``, ``fastapi_service``,
``tcp_server_client``, ``cli``. Each folder is a small working project with its own passing tests plus a
``template.json`` (name, description, keywords, entry points). A template is used only when a task starts from an
empty workspace (the plan's *design* step): keyword rules on the objective, criteria and requirements pick it; the
``classify`` role decides only when no rule matches.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from hmap.agents.coding.workspace import Workspace, skipped

TEMPLATES_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = "python_package"


@dataclass(frozen=True)
class Template:
    name: str
    description: str
    keywords: tuple[str, ...]
    entry_points: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    folder: Path = field(default=TEMPLATES_DIR)

    def files(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in sorted(self.folder.rglob("*")):
            rel = p.relative_to(self.folder).as_posix()
            if p.is_file() and rel != "template.json" and not skipped(rel):
                out[rel] = p.read_text(encoding="utf-8")
        return out

    def install(self, ws: Workspace) -> list[str]:
        files = self.files()
        for rel, text in files.items():
            ws.write(rel, text)
        return sorted(files)


def all_templates() -> dict[str, Template]:
    out: dict[str, Template] = {}
    for meta in sorted(TEMPLATES_DIR.glob("*/template.json")):
        d = json.loads(meta.read_text(encoding="utf-8"))
        out[d["name"]] = Template(name=d["name"], description=d["description"], keywords=tuple(d["keywords"]),
                                  entry_points=tuple(d.get("entry_points", [])), requires=tuple(d.get("requires", [])),
                                  folder=meta.parent)
    return out


def score(template: Template, text: str) -> int:
    low = f" {text.lower()} "
    return sum(len(re.findall(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", low)) for k in template.keywords)


def choose(text: str) -> tuple[str | None, dict[str, int]]:
    """The template whose keywords occur most in ``text`` (None when nothing matches or two tie at the top)."""
    scores = {name: score(t, text) for name, t in all_templates().items()}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] == 0 or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None, scores
    return ranked[0][0], scores
