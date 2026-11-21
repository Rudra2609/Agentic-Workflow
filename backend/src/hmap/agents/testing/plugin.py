"""Member 8 plug-in: automated testing & execution (Sprint 8).

- ``TestingAgent`` serves ``test.run`` (priority 100: the stub stands down).
- hook ``on_tests_done``: emits ``test.completed`` and drives the test -> ``code.revise`` -> test loop.
- router ``/api/testing`` (auto-mounted); UI ``frontend/src/features/testing/`` (auto-registered).
"""

from hmap.agents.testing.agent import TestingAgent
from hmap.agents.testing.hooks import on_tests_done
from hmap.agents.testing.router import router
from hmap.core.plugins import Plugin

PLUGIN = Plugin(
    name="testing",
    agents=[TestingAgent],
    router=router,
    manager_hooks=[on_tests_done],
    priority=100,
    description="Automated testing: runs a coding step's workspace through static, build, unit, integration, "
                "security and execution stages in a locked-down Docker sandbox (or the local jailed runner), "
                "explains each failure with a hint, writes tests from the acceptance criteria when there are none, "
                "and sends real failures back to the coding agent for a bounded number of rounds.",
)
