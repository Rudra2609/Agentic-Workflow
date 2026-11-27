"""Member 11 plug-in: local models, routing, benchmarking and fine-tuning (Sprint 11).

- strategy slot ``llm_provider``: :class:`~hmap.agents.models.router.ModelRouter` (``HMAP_ROUTER=on``; ``off`` = the
  role maps, exactly as before);
- router ``/api/models`` (auto-mounted): registry, hardware, route decisions (+ stream), benchmarks, fine-tune runs;
  UI ``frontend/src/features/models/`` (auto-registered).
No agent: nothing in the task graph is a "models" capability.
"""

from hmap.agents.models.api import router
from hmap.agents.models.router import ModelRouter
from hmap.core.plugins import Plugin

PLUGIN = Plugin(
    name="models",
    router=router,
    provides={"llm_provider": ModelRouter},
    priority=100,
    description="Local models and routing: the model registry, memory feasibility, backends (Ollama, MLX, "
                "llama.cpp, the cloud key pool), a swap-aware scheduler, benchmarks on every member's gold sets and "
                "the router that orders the routes of each call (HMAP_ROUTER) and logs why.",
)
