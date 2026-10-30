"""Member 6 plug-in: research verification (Sprint 6).

- ``VerifyAgent`` serves ``verify.claims`` (priority 100: the stub stands down).
- hook ``on_verified``: emits ``verification.completed`` and runs the bounded follow-up research loop (item 6.8).
- router ``/api/verify`` (auto-mounted); UI ``frontend/src/features/verify/`` (auto-registered).
"""

from hmap.agents.verify.agent import VerifyAgent
from hmap.agents.verify.hooks import on_verified
from hmap.agents.verify.router import router
from hmap.core.plugins import Plugin

PLUGIN = Plugin(
    name="verify",
    agents=[VerifyAgent],
    router=router,
    manager_hooks=[on_verified],
    priority=100,
    description="Research verification: checks every claim of a ResearchReport in four layers (verbatim quote + "
                "hash, entailment, the verifier's own searches, cross-source conflicts) and asks for follow-up "
                "research on what it cannot confirm.",
)
