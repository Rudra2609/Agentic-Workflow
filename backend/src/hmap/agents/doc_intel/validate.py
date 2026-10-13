"""Validation (spec item 2.7): the guarantees handed to Member 3 (spec §7). Problems that a person should look at
become ``open_questions``; output that breaks the contract raises (and the task fails instead of passing on bad data).
"""

from dataclasses import dataclass, field

from hmap.core.contracts.domain import RequirementSet

MARKS_TOLERANCE = 0.01


@dataclass
class Report:
    issues: list[str] = field(default_factory=list)       # for the log / eval
    questions: list[str] = field(default_factory=list)    # added to open_questions


def check(rs: RequirementSet, stated_totals: list[float]) -> Report:
    report = Report()
    criteria_sum = sum(e.max_marks for e in rs.evaluation_criteria)
    if stated_totals and rs.evaluation_criteria:
        stated = sum(stated_totals)
        if abs(criteria_sum - stated) > MARKS_TOLERANCE:
            msg = (f"The marking criteria add up to {criteria_sum:g} marks, but the document states a total of "
                   f"{stated:g}. Which is right?")
            report.issues.append("marks_sum_mismatch")
            report.questions.append(msg)
    for e in rs.evaluation_criteria:
        levels = [lv.marks for lv in e.rubric_levels if lv.marks is not None]
        if levels and max(levels) > e.max_marks + MARKS_TOLERANCE:
            report.issues.append(f"{e.id}: a rubric level gives more than the criterion's maximum")
            report.questions.append(f"'{e.criterion}' has a level worth {max(levels):g} marks but a maximum of "
                                    f"{e.max_marks:g}. Which is right?")
    for r in rs.requirements:
        if not r.source_ref.quote:
            report.issues.append(f"{r.id}: no verified quote")
    if not rs.requirements:
        report.issues.append("no_requirements")
        report.questions.append("No requirements were found in the uploaded documents. Is this the right file?")
    return report
