"""Model backends behind one interface (item 11.3): Ollama, ``mlx_lm.server``, llama.cpp ``llama-server`` and the
Sprint-1 cloud key pool. See :mod:`hmap.agents.models.backends.base`."""

from hmap.agents.models.backends.base import Backend, Health, build_backends
from hmap.agents.models.backends.cloud import CloudPoolBackend
from hmap.agents.models.backends.local import OllamaBackend, OpenAILocalBackend

__all__ = ["Backend", "CloudPoolBackend", "Health", "OllamaBackend", "OpenAILocalBackend", "build_backends"]
