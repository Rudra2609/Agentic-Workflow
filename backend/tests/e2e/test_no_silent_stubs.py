"""Item 10.19 "no silent stubs" (Member 10): every pipeline capability is served by a real agent (none is left after
Sprint 10), every stub that remains is flagged as one (``is_stub`` -> ``stub`` in ``GET /agents/capabilities`` and
"placeholder" in the dashboard), and the README's real-vs-stub table says the same as the code. Runs in pre-commit,
so every ``check_sprint`` fails when a stub is unflagged or the table lies."""

import re
from pathlib import Path
from typing import ClassVar

from hmap.core.contracts import TaskAssign, TaskResult
from hmap.core.contracts.capabilities import STUBBED_CAPABILITIES
from hmap.core.plugins import Plugin
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.runtime.discovery import CapabilityRow, capability_table, discover

README = Path(__file__).resolve().parents[3] / "README.md"


def silent_stubs(rows: list[CapabilityRow], plugins: list[Plugin]) -> list[str]:
    """Agents that look like stubs (named ``stub-*`` or shipped by the ``stubs`` plug-in) but do not say so."""
    out = []
    for p in plugins:
        for agent in p.agents:
            if (agent.name.startswith("stub-") or p.name == "stubs") and not agent.is_stub:
                out.append(f"{p.name}:{agent.name}")
    return out


def readme_status() -> dict[str, str]:
    """capability -> status column of the README table (`code` names in the first column)."""
    out: dict[str, str] = {}
    for line in README.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        for cap in re.findall(r"`([a-z]+\.[a-z_.*]+)`", cells[0]):
            out[cap] = cells[1].strip("* ").lower()
    return out


def test_every_pipeline_capability_is_real() -> None:
    plugins = discover()
    rows = {r.capability: r for r in capability_table(plugins, expected=STUBBED_CAPABILITIES)}
    not_real = [c for c in STUBBED_CAPABILITIES if rows[c].status != "real"]
    assert not not_real, f"still stubs or missing: {not_real}"
    assert not silent_stubs(list(rows.values()), plugins)


def test_readme_table_matches_the_code() -> None:
    table = readme_status()
    rows = {r.capability: r.status for r in capability_table(discover(), expected=STUBBED_CAPABILITIES)}
    for cap in STUBBED_CAPABILITIES:
        assert cap in table, f"{cap} missing from the README's real-vs-stub table"
        assert table[cap] == rows[cap], f"README says {cap} is {table[cap]!r}, the code says {rows[cap]!r}"


class Pretender(BaseAgent):
    """A placeholder that forgot to set ``is_stub``: the check must catch it."""

    name = "stub-pretend"
    capabilities: ClassVar[tuple[str, ...]] = ("review.final",)

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        return ctx.result([], summary="placeholder")


def test_an_unflagged_stub_is_caught() -> None:
    plugins = [Plugin(name="pretend", agents=[Pretender], priority=500)]
    rows = capability_table(plugins, expected=STUBBED_CAPABILITIES)
    assert silent_stubs(rows, plugins) == ["pretend:stub-pretend"]
    assert {r.capability: r.status for r in rows}["document.extract"] == "missing"
