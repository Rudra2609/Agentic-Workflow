"""Dependency audit (Sprint 8 item 8.6, the "pip-audit" part; research §3).

The sandbox has no network, so the audit runs on the host and never executes project code: it only *reads*
``requirements*.txt``, ``pyproject.toml`` (``[project] dependencies``) and ``package.json`` (``dependencies`` /
``devDependencies``), takes the **pinned** versions (``name==1.2.3``; npm exact versions ``1.2.3``), and asks the OSV
database (https://osv.dev, ``POST /v1/querybatch``, the source pip-audit and npm audit also use) which of them have
known vulnerabilities. Unpinned dependencies cannot be audited and are listed as such.

``HMAP_TESTING_DEP_AUDIT``: ``auto`` (ask OSV, 8 s limit, fall back to the cache), ``offline`` (cache only:
``data/testing/osv_cache.json``, git-ignored), ``off``. No network or no answer → the stage detail says "not
audited"; it never fails a run by itself. A vulnerable pin is a SECURITY failure on the line that pins it, with the
fixed version as the hint, and it can go to Member 7 like any other security finding.
"""

import json
import re
import tomllib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hmap.agents.testing.model import FailureRecord
from hmap.core.config import REPO_ROOT
from hmap.core.tracing import get_logger

log = get_logger("hmap.testing.deps")

OSV_URL = "https://api.osv.dev/v1/querybatch"
CACHE = REPO_ROOT / "data" / "testing" / "osv_cache.json"
TIMEOUT_S = 8.0
_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9.+!_-]+)\s*(?:[;#].*)?$")
_NPM_EXACT = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

Query = Callable[[list[dict[str, Any]]], Awaitable[list[list[dict[str, Any]]]]]


@dataclass
class Dep:
    ecosystem: str          # "PyPI" | "npm"
    name: str
    version: str
    file: str
    line: int


@dataclass
class AuditResult:
    audited: list[str] = field(default_factory=list)
    unpinned: list[str] = field(default_factory=list)
    vulnerable: list[dict[str, Any]] = field(default_factory=list)
    source: str = "none"              # "osv" | "cache" | "none"
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"audited": self.audited, "unpinned": self.unpinned, "vulnerable": self.vulnerable,
                "source": self.source, "note": self.note}


def _line_of(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return i
    return 1


def find(files: dict[str, str]) -> tuple[list[Dep], list[str]]:
    deps: list[Dep] = []
    unpinned: list[str] = []
    for rel, text in sorted(files.items()):
        name = rel.rsplit("/", 1)[-1]
        if "node_modules/" in rel:
            continue
        if name.startswith("requirements") and name.endswith(".txt"):
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", "-")):
                    continue
                m = _REQ.match(stripped)
                if m:
                    deps.append(Dep("PyPI", m.group(1).lower(), m.group(2), rel, i))
                else:
                    unpinned.append(f"{rel}: {stripped[:80]}")
        elif name == "pyproject.toml":
            try:
                project = tomllib.loads(text).get("project", {})
            except tomllib.TOMLDecodeError:
                continue
            for spec in project.get("dependencies", []):
                m = _REQ.match(str(spec))
                if m:
                    deps.append(Dep("PyPI", m.group(1).lower(), m.group(2), rel, _line_of(text, str(spec))))
                else:
                    unpinned.append(f"{rel}: {str(spec)[:80]}")
        elif name == "package.json":
            try:
                pkg = json.loads(text)
            except ValueError:
                continue
            for section in ("dependencies", "devDependencies"):
                for dep, ver in (pkg.get(section) or {}).items():
                    if isinstance(ver, str) and _NPM_EXACT.match(ver):
                        deps.append(Dep("npm", dep, ver, rel, _line_of(text, f'"{dep}"')))
                    else:
                        unpinned.append(f"{rel}: {dep}@{ver}")
    return deps, unpinned


def _key(d: Dep) -> str:
    return f"{d.ecosystem}:{d.name}=={d.version}"


def _load_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        data: dict[str, list[dict[str, Any]]] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, ValueError):
        return {}


def _save_cache(path: Path, cache: dict[str, list[dict[str, Any]]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


async def osv_query(queries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """One batch request to OSV; per query the list of advisories (id, summary when present)."""
    import httpx

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        resp = await client.post(OSV_URL, json={"queries": queries})
        resp.raise_for_status()
        results = resp.json().get("results", [])
        out: list[list[dict[str, Any]]] = []
        for r in results:
            vulns = r.get("vulns") or []
            out.append([{"id": v.get("id"), "modified": v.get("modified")} for v in vulns])
        details: list[list[dict[str, Any]]] = []
        for vulns in out:
            row = []
            for v in vulns[:5]:
                try:
                    d = (await client.get(f"https://api.osv.dev/v1/vulns/{v['id']}")).json()
                except Exception:
                    d = {}
                row.append({"id": v["id"], "summary": str(d.get("summary") or d.get("details") or "")[:200],
                            "fixed": fixed_versions(d)})
            details.append(row)
        return details


def highest(versions: list[str]) -> str | None:
    """The newest of the fixed versions (a pin at or above it is safe from every listed advisory)."""
    from packaging.version import InvalidVersion, Version

    best: tuple[Version, str] | None = None
    for v in versions:
        try:
            parsed = Version(v)
        except InvalidVersion:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, v)
    return best[1] if best else (versions[0] if versions else None)


def fixed_versions(advisory: dict[str, Any]) -> list[str]:
    out = []
    for affected in advisory.get("affected", []):
        for rng in affected.get("ranges", []):
            for ev in rng.get("events", []):
                if "fixed" in ev:
                    out.append(str(ev["fixed"]))
    return sorted(set(out))[:5]


async def audit(files: dict[str, str], mode: str, *, query: Query | None = None,
                cache_path: Path = CACHE) -> tuple[AuditResult, list[FailureRecord]]:
    deps, unpinned = find(files)
    res = AuditResult(audited=[_key(d) for d in deps], unpinned=unpinned)
    if mode == "off" or not deps:
        res.note = "dependency audit off" if mode == "off" else "no pinned dependencies to audit"
        return res, []
    cache = _load_cache(cache_path)
    missing = [d for d in deps if _key(d) not in cache]
    if missing and mode == "auto":
        try:
            rows = await (query or osv_query)([{"package": {"name": d.name, "ecosystem": d.ecosystem},
                                                "version": d.version} for d in missing])
            for d, row in zip(missing, rows, strict=False):
                cache[_key(d)] = row
            _save_cache(cache_path, cache)
            res.source = "osv"
        except Exception as exc:          # no network, OSV down: the cache is all we have
            log.info("osv query failed", error=type(exc).__name__)
            res.note = f"OSV not reachable ({type(exc).__name__}): cached answers only"
    known = [d for d in deps if _key(d) in cache]
    if not known:
        res.note = res.note or "not audited: no cached answer (HMAP_TESTING_DEP_AUDIT=offline)"
        return res, []
    if res.source == "none":
        res.source = "cache"
    failures = []
    for d in known:
        advisories = cache[_key(d)]
        if not advisories:
            continue
        for adv in advisories:
            res.vulnerable.append({"dependency": _key(d), **adv})
        first = advisories[0]
        more = f" (+{len(advisories) - 1} more)" if len(advisories) > 1 else ""
        target = highest([v for adv in advisories for v in adv.get("fixed") or []])
        failures.append(FailureRecord(
            stage="security", category="SECURITY", file=d.file, line=d.line,
            message=(f"HMAP-D1 {d.name} {d.version} has {len(advisories)} known vulnerabilit"
                     f"{'y' if len(advisories) == 1 else 'ies'}: {first.get('id')} {first.get('summary') or ''}"
                     f"{more}").strip()[:400],
            hint=f"pin {d.name} to {target} or newer" if target else f"upgrade {d.name} to a fixed release"))
    if len(known) < len(deps):
        res.note = (res.note + "; " if res.note else "") + f"{len(deps) - len(known)} pinned dependencies not audited"
    return res, failures
