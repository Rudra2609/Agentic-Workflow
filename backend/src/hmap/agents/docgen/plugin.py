"""Member 9 plug-in: technical documentation (Sprint 9).

- ``DocAgent`` serves ``docs.generate`` and ``docs.update`` (priority 100: the stub stands down).
- hooks: ``docs.completed`` after every docs step; ``code.completed`` -> ``docs.update`` when documents exist.
- router ``/api/docgen`` (auto-mounted); UI ``frontend/src/features/docgen/`` (auto-registered).
"""

from hmap.agents.docgen.agent import DocAgent
from hmap.agents.docgen.hooks import on_code_completed, on_docs_done, on_docs_updated
from hmap.agents.docgen.router import router
from hmap.core.plugins import Plugin

PLUGIN = Plugin(
    name="docgen",
    agents=[DocAgent],
    router=router,
    manager_hooks=[on_docs_done, on_docs_updated, on_code_completed],
    priority=100,
    description="Technical documentation: writes the README, API reference, architecture (Mermaid), code summaries "
                "and report sections from the facts of the actual code (or, for a report project, from the verified "
                "research), checks every technical claim against the code, runs the documented examples in the "
                "testing sandbox and removes what the code does not support.",
)
