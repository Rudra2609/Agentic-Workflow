"""Facts from manifests and infrastructure files (Sprint 9 item 9.1): declared dependencies
(``requirements*.txt``, ``pyproject.toml`` incl. extras and ``[project.scripts]``, ``package.json``), Docker /
compose services, Makefile targets, and ports named in those files or in shell scripts."""

import json
import re
import tomllib

from hmap.agents.docgen.model import Facts

COMPOSE_FILE = re.compile(r"(docker-)?compose[.\w-]*\.ya?ml")      # docker-compose.obs.yml too
COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
PORT_IN_TEXT = re.compile(r"(?:--port[ =]|localhost:|127\.0\.0\.1:|0\.0\.0\.0:|\"(\d{2,5}):\d{2,5}\"|-p )(\d{2,5})")


def requirement_name(spec: str) -> tuple[str, str]:
    m = re.match(r"\s*([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)", spec)
    if not m:
        return spec.strip().lower(), ""
    return m.group(1).lower().replace("_", "-"), m.group(3).split(";")[0].strip()


def read_manifest(rel: str, text: str, facts: Facts) -> None:
    name = rel.rsplit("/", 1)[-1]
    if name.startswith("requirements") and name.endswith(".txt"):
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                dep, spec = requirement_name(line)
                facts.dependencies.setdefault(dep, spec)
    elif name == "pyproject.toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            facts.notes.append(f"{rel}: not valid TOML ({exc})")
            return
        project = data.get("project", {})
        facts.python_requires = facts.python_requires or project.get("requires-python")
        groups = dict(project.get("optional-dependencies", {}))
        groups.update(data.get("dependency-groups", {}) or {})
        facts.extras = sorted(set(facts.extras) | set(project.get("optional-dependencies", {})))
        for spec in [*project.get("dependencies", []), *[s for g in groups.values() for s in g if isinstance(s, str)]]:
            dep, version = requirement_name(spec)
            facts.dependencies.setdefault(dep, version)
        for script, target in (project.get("scripts") or {}).items():
            facts.scripts[script] = str(target)
    elif name == "package.json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            facts.notes.append(f"{rel}: not valid JSON")
            return
        if not isinstance(data, dict):
            return
        for group in ("dependencies", "devDependencies"):
            for dep, version in (data.get(group) or {}).items():
                facts.dependencies.setdefault(str(dep).lower(), str(version))
        for script, cmd in (data.get("scripts") or {}).items():
            facts.scripts.setdefault(f"npm run {script}", str(cmd))
        facts.technologies.append("node")
    elif name == "Dockerfile" or name.startswith("Dockerfile."):
        facts.technologies.append("docker")
        facts.ports += [int(p) for p in re.findall(r"^\s*EXPOSE\s+(\d{2,5})", text, re.M)]
    elif name in COMPOSE_NAMES or COMPOSE_FILE.fullmatch(name):
        facts.technologies.append("docker")
        facts.services += _compose_services(text)
        facts.ports += [int(a) for a, _ in re.findall(r"[\"']?(?:[\d.]+:)?(\d{2,5}):(\d{2,5})[\"']?", text)]
    elif name == ".gitignore":
        base = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "!")):
                facts.ignored.append(base + line.lstrip("/"))
    elif name == "Makefile":
        facts.make_targets += [t for t in re.findall(r"^([A-Za-z0-9][\w.-]*):(?!=)", text, re.M)
                               if t not in (".PHONY",)]
    if name.endswith(".sh"):                       # ${HMAP_DEMO_NO_OPEN:-} in a script is a setting it reads
        for var in re.findall(r"\$\{([A-Z][A-Z0-9]*_[A-Z0-9_]+)", text):
            facts.env.setdefault(var, None)
    if name == "Makefile" or name.endswith((".sh", ".service")) or COMPOSE_FILE.fullmatch(name):
        for m in PORT_IN_TEXT.finditer(text):
            port = int(m.group(2) or m.group(1))
            if 1 <= port <= 65535:
                facts.ports.append(port)


def _compose_services(text: str) -> list[str]:
    """Names under ``services:`` (two-space or tab indented keys); no YAML library needed."""
    out: list[str] = []
    inside = False
    indent: int | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^services:\s*$", line):
            inside, indent = True, None
            continue
        if inside:
            if not line.startswith((" ", "\t")):
                break
            lead = len(line) - len(line.lstrip())
            if indent is None:
                indent = lead
            if lead == indent and (m := re.match(r"\s*([\w.-]+):\s*$", line)):
                out.append(m.group(1))
    return out
