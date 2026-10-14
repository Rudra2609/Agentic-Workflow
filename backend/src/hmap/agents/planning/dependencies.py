"""Dependency inference (spec item 3.3). Three sources, merged:

- **template / rule** edges: design before every build step; one part before another when its requirements say so
  ("extend your Part A server");
- **data-flow** edges from what each capability consumes (``CAPABILITY_OUTPUTS``): a test needs the code it tests,
  documentation needs tested code, verification needs a research report;
- **model** edges proposed in the decomposition, kept when they join real steps; if they close a cycle the validator
  drops the least trusted edge (model edges first). A build step may wait for a check of an earlier design step.

The final review (single sink) and orphan / cycle handling are the validator's job (``validate.repair``).
"""

import re

from hmap.agents.planning.model import WorkingPlan
from hmap.agents.planning.skeleton import Part
from hmap.core.contracts.capabilities import RESEARCH_RUN, VERIFY_CLAIMS


def infer(plan: WorkingPlan, parts: list[Part], part_tasks: dict[str, list[str]]) -> None:
    by_id = {t.id: t for t in plan.tasks}
    builds = {pid: [t for t in ids if by_id[t].phase == "implement"] for pid, ids in part_tasks.items()}
    tests = {pid: [t for t in ids if by_id[t].phase == "test"] for pid, ids in part_tasks.items()}

    # design -> every build step (transitive reduction later removes the redundant ones)
    if "design" in by_id:
        for ids in builds.values():
            for b in ids:
                plan.add_edge("design", b, "template")

    # data flow: a test step needs the code it checks (shared requirements), else every build step of its part
    for pid, test_ids in tests.items():
        for test_id in test_ids:
            reqs = set(by_id[test_id].requirement_ids)
            mine = [b for b in builds[pid] if reqs & set(by_id[b].requirement_ids)] or builds[pid]
            for b in mine:
                plan.add_edge(b, test_id, "dataflow")

    # data flow: documents describe tested work
    all_tests = [t for ids in tests.values() for t in ids]
    all_builds = [b for ids in builds.values() for b in ids]
    for t in plan.tasks:
        if t.phase == "document":
            for dep in all_tests or all_builds:
                plan.add_edge(dep, t.id, "dataflow")

    # data flow: verification needs research reports; extra research steps feed the design via verify
    if "verify" in by_id:
        for t in plan.tasks:
            if t.agent_capability == RESEARCH_RUN and t.id != "research":
                plan.add_edge(t.id, "verify", "dataflow")
    for t in plan.tasks:
        if t.agent_capability == VERIFY_CLAIMS and t.phase == "test":
            for dep in all_builds:
                plan.add_edge(dep, t.id, "dataflow")

    # rule: a part whose requirements name another part builds on it ("reuse your Part A server")
    for part in parts:
        if not part.name:
            continue
        for other in parts:
            if other is part or not other.name:
                continue
            pattern = re.compile(rf"\b{re.escape(other.name)}\b", re.I)
            if any(pattern.search(r.text) for r in part.requirements):
                for b in builds.get(part.id, []):
                    for ob in builds.get(other.id, []):
                        plan.add_edge(ob, b, "rule")

