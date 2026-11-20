"""Member 7 plug-in: autonomous coding (Sprint 7).

- ``CodingAgent`` serves ``code.implement`` and ``code.revise`` (priority 100: the ``code.implement`` stub stands
  down; ``code.revise`` never had a stub).
- hooks ``on_code_implemented`` / ``on_code_revised``: emit ``code.completed``.
- router ``/api/coding`` (auto-mounted); UI ``frontend/src/features/coding/`` (auto-registered).
"""

from hmap.agents.coding.agent import CodingAgent
from hmap.agents.coding.hooks import on_code_implemented, on_code_revised
from hmap.agents.coding.router import router
from hmap.core.plugins import Plugin

PLUGIN = Plugin(
    name="coding",
    agents=[CodingAgent],
    router=router,
    manager_hooks=[on_code_implemented, on_code_revised],
    priority=100,
    description="Autonomous coding: starts from the project's workspace (or a template), finds the files to change, "
                "edits them with SEARCH/REPLACE blocks, runs the checks in a jailed runner, debugs, and returns a "
                "CodeChangeSet with the diff and a tool-call trace.",
)
