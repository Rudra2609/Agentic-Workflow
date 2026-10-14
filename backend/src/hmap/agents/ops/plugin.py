"""Member 4 plug-in: operations (Sprint 4 §5b, plan D12). No agents: the "why did this task fail?" view, the DLQ list
and the explicit "replay as a new attempt" action, behind ``/api/ops`` and the dashboard's Operations page.
Kept separate from the refinement library so the two never block each other (spec §5b)."""

from hmap.agents.ops.router import router
from hmap.core.plugins import Plugin

PLUGIN = Plugin(
    name="ops",
    router=router,
    priority=100,
    description="Operations: why did a task fail, dead letters and their replay, links to traces and dashboards.",
)
