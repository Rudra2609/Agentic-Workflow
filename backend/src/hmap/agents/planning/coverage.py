"""Coverage and traceability (spec item 3.6): requirement -> the build / test / document steps that serve it, and
every requirement either covered or flagged with a reason. The final review checks everything, so it does not
count as coverage."""

from dataclasses import dataclass, field

from hmap.agents.planning.validate import WORK_PHASES
from hmap.core.contracts.domain import PlanTask, RequirementSet


@dataclass
class CoverageReport:
    matrix: dict[str, list[str]] = field(default_factory=dict)
    covered: list[str] = field(default_factory=list)
    flagged: dict[str, str] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        """Share of requirements that are covered or explicitly flagged (the spec's target: 1.0)."""
        total = len(self.covered) + len(self.flagged) + len(self.uncovered)
        return 1.0 if total == 0 else (len(self.covered) + len(self.flagged)) / total


def coverage(tasks: list[PlanTask], rs: RequirementSet, flagged: dict[str, str] | None = None) -> CoverageReport:
    flagged = dict(flagged or {})
    report = CoverageReport()
    for r in rs.requirements:
        ids = [t.id for t in tasks if t.phase in WORK_PHASES and r.id in t.requirement_ids]
        report.matrix[r.id] = ids
        if ids:
            report.covered.append(r.id)
        elif r.id in flagged:
            report.flagged[r.id] = flagged[r.id]
        else:
            report.uncovered.append(r.id)
    return report
