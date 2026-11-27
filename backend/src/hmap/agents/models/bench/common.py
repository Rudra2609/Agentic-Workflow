"""Shared pieces: where results go, model ids → a gateway that can only reach that model."""

import re
import sys
from pathlib import Path
from typing import Any

from hmap.core.config import CLOUD_CHAT_ROLES, CLOUD_PROVIDERS, LLMMode, Settings
from hmap.core.llm import CloudRouter, Gateway, LLMResponse
from hmap.core.llm.errors import LLMProviderError
from hmap.core.llm.providers.base import ChatRequest

ROOT = Path(__file__).resolve().parents[6]
SAMPLES = ROOT / "samples" / "models"
RESULTS = SAMPLES / "bench" / "results"
CACHE = ROOT / "samples" / "llm_cache" / "models"
BAKEOFF_SCRIPTS = ROOT / "scripts"


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_")


def is_cloud(model: str) -> bool:
    """``groq:...`` / ``gemini:...`` (a key-pool route) vs an Ollama tag such as ``qwen3.5:9b``."""
    return model.partition(":")[0] in CLOUD_PROVIDERS


def bakeoff() -> Any:
    """The §0 harness module (prompts, schemas, scoring); a plain script, imported from ``scripts/``."""
    if str(BAKEOFF_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(BAKEOFF_SCRIPTS))
    import model_bakeoff

    return model_bakeoff


class NoLocal:
    """The local step for a cloud model under test: never answer with another model (a fallback would measure the
    wrong model)."""

    name = "none"

    async def chat(self, request: ChatRequest) -> LLMResponse:
        raise LLMProviderError("cloud route not answering (rate limited / cooling); no local fallback in a benchmark")

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        raise LLMProviderError("no embeddings in this benchmark")


def env_for(model: str, base: Settings) -> dict[str, str]:
    """Environment for a member's evaluator so every chat role uses ``model`` and nothing else."""
    if is_cloud(model):
        provider, _, name = model.partition(":")
        routes = ",".join(f"{r}={provider}:{name}" for r in sorted(CLOUD_CHAT_ROLES))
        # the gateway resolves the local model before trying the cloud: a name no Ollama has, so a call the cloud
        # does not answer fails instead of being answered by another model
        local = ",".join(f"{r}=no-local-fallback" for r in sorted(CLOUD_CHAT_ROLES))
        return {"HMAP_CLOUD_ROLE_MAP": routes, "HMAP_ROLE_MAP": f"{local},embed=nomic-embed-text",
                "HMAP_CLOUD_OK": "true"}
    roles = ",".join(f"{r}={model}" for r in sorted(CLOUD_CHAT_ROLES)) + ",embed=nomic-embed-text"
    return {"HMAP_ROLE_MAP": roles, "HMAP_CLOUD_OK": "false", "HMAP_CLOUD_ROLE_MAP": ""}


def gateway_for(model: str, base: Settings, mode: LLMMode, *, cache_root: Path | None = None,
                max_repairs: int = 0) -> Gateway:
    """A gateway whose every chat role is ``model`` (local: Ollama only; cloud: that route only, no local
    fallback). Records / replays under ``samples/llm_cache/models/<model>/``. ``max_repairs=0``: no repair retries,
    as in the bake-off, so invalid JSON counts."""
    root = cache_root or CACHE / slug(model)
    if is_cloud(model):
        provider, _, name = model.partition(":")
        # role map: a placeholder (the gateway resolves the local model first; NoLocal answers for it)
        s = base.model_copy(update={"llm_mode": mode, "llm_cache_dir": root, "cloud_ok": True,
                                    "role_map": {r: "no-local-fallback" for r in CLOUD_CHAT_ROLES},
                                    "cloud_role_map": {r: [(provider, name)] for r in CLOUD_CHAT_ROLES}})
        router = CloudRouter.from_settings(s) if mode in ("live", "record") else None
        return Gateway(s, local=NoLocal(), cloud_router=router, mode=mode, max_repairs=max_repairs,
                       plugin="bench")
    s = base.model_copy(update={"llm_mode": mode, "llm_cache_dir": root, "cloud_ok": False,
                                "role_map": {r: model for r in CLOUD_CHAT_ROLES}, "cloud_role_map": {}})
    return Gateway(s, mode=mode, max_repairs=max_repairs, plugin="bench")
