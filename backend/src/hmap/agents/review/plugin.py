"""Member 10 plug-in: final review & recovery (Sprint 10).

- ``ReviewAgent`` serves ``review.final`` (priority 100: the stub stands down).
- strategy slot ``recovery``: ``ReviewRecovery`` (the task table for the review; revise / rerun / replan / escalate
  when the run settles; bounded rounds).
- hook: ``review.completed`` after every review.
- router ``/api/review`` (auto-mounted); UI ``frontend/src/features/review/`` (auto-registered).
"""

from hmap.agents.review.agent import ReviewAgent
from hmap.agents.review.hooks import on_review_done
from hmap.agents.review.recovery import ReviewRecovery
from hmap.agents.review.router import router
from hmap.core.plugins import Plugin

PLUGIN = Plugin(
    name="review",
    agents=[ReviewAgent],
    router=router,
    manager_hooks=[on_review_done],
    provides={"recovery": ReviewRecovery},
    priority=100,
    description="Final review & recovery: judges the finished work requirement by requirement (objective evidence "
                "first, an LLM judge second with order swap and votes), names the step that caused each failure, "
                "and drives a bounded revise -> re-test -> re-document -> re-review loop, or asks a person.",
)
