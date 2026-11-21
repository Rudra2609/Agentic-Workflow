"""Resource governance for a 16 GB laptop (Sprint 8 item 8.11, plan D11).

- One sandbox run at a time per process (``HMAP_TESTING_CONCURRENCY``, default 1): the stack, Ollama and a 256 MB
  container fit together; two parallel test steps queue instead of competing for memory.
- Leftover sandbox containers (a crashed process, a killed demo) are removed when the agent starts
  (:func:`~.sandbox.docker.reap`).
- The image is never pulled or built during a task (``make sandbox-image``); its presence is checked once a minute.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from hmap.core.config import Settings

_SEMAPHORES: dict[tuple[int, int], asyncio.Semaphore] = {}


def _semaphore(settings: Settings) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = (id(loop), settings.testing_concurrency)
    sem = _SEMAPHORES.get(key)
    if sem is None:
        if len(_SEMAPHORES) > 32:
            _SEMAPHORES.clear()
        sem = _SEMAPHORES[key] = asyncio.Semaphore(settings.testing_concurrency)
    return sem


@asynccontextmanager
async def slot(settings: Settings) -> AsyncIterator[None]:
    async with _semaphore(settings):
        yield


def waiting(settings: Settings) -> bool:
    """True when a run would have to wait (for the UI's progress text)."""
    return _semaphore(settings).locked()


async def startup_cleanup(settings: Settings) -> int:
    if settings.testing_sandbox == "local":
        return 0
    from hmap.agents.testing.sandbox.docker import reap

    try:
        return await reap()
    except Exception:     # Docker absent or not running: nothing to clean
        return 0
