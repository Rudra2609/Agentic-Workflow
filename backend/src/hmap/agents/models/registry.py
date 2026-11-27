"""Model registry (item 11.1): every model the platform can use, as ``ModelSpec`` rows.

Sources, merged on :meth:`ModelRegistry.sync`:
- **Ollama**: ``/api/tags`` (installed models, digests, sizes, quant), ``/api/show`` (family, parameters, context),
  ``/api/ps`` (loaded right now), and the GGUF header of the weights file when ``OLLAMA_MODELS`` is readable;
- **cloud**: the team key pool's routes (``HMAP_CLOUD_ROLE_MAP``): ``available`` when that provider has keys,
  ``missing`` when not;
- **MLX / llama.cpp** servers that answer at ``HMAP_MLX_BASE_URL`` / ``HMAP_LLAMACPP_BASE_URL`` (``/v1/models``);
- the **snapshot** (``samples/models/data/model_specs.json``) when Ollama is not running, so the registry, the
  hardware page and the router still know the local models (status ``available``: on disk, not verified now).

``roles_ok`` = the roles the role maps give a model, plus the roles the benchmark found it fit for. A person can
disable a model (the router never picks it) or pin it (the release freeze, item 11.24); both survive a sync.
"""

import contextlib
import os
from pathlib import Path
from typing import Any

import httpx

from hmap.agents.models import gguf
from hmap.agents.models.hardware import GB, snapshot_specs
from hmap.agents.models.model import ModelRow
from hmap.agents.models.store import ModelStore
from hmap.core.config import Settings
from hmap.core.contracts.domain import ModelSpec
from hmap.core.tracing import get_logger

log = get_logger("hmap.models.registry")
DEFAULT_OLLAMA_MODELS = Path("/Volumes/Tirth_SSD/ollama")
# Context windows of the cloud models in the default routes (provider documentation, checked 2026-10-12)
CLOUD_CTX = {"gemini": 1_048_576, "groq": 131_072}


def _params_b(label: str) -> float | None:
    try:
        return float(label.upper().rstrip("B")) if label else None
    except ValueError:
        return None


def roles_for(model: str, settings: Settings) -> list[str]:
    local = [role for role, m in settings.role_map.items() if m == model]
    cloud = [role for role, routes in settings.cloud_role_map.items() if any(f"{p}:{m}" == model for p, m in routes)]
    return sorted(set(local + cloud))


def from_snapshot(settings: Settings) -> list[ModelRow]:
    rows = []
    for name, meta in snapshot_specs().items():
        rows.append(ModelRow(source="snapshot", details=meta, spec=ModelSpec(
            id=name, family=str(meta.get("architecture", "")), params_b=_params_b(str(meta.get("size_label", ""))),
            quant=meta.get("quant"), ctx=meta.get("context_length"), backend="ollama",
            mem_gb=round(int(meta.get("file_bytes", 0)) / GB, 2) or None, roles_ok=roles_for(name, settings),
            status="available")))
    return rows


def cloud_rows(settings: Settings) -> list[ModelRow]:
    seen: dict[str, ModelRow] = {}
    for routes in settings.cloud_role_map.values():
        for provider, model in routes:
            mid = f"{provider}:{model}"
            if mid in seen:
                continue
            keys = len(settings.cloud_keys(provider))
            has_keys = bool(keys)
            seen[mid] = ModelRow(source="cloud", details={"provider": provider, "keys": keys},
                                 spec=ModelSpec(id=mid, family=model.split("/")[0], backend="cloud",
                                                ctx=CLOUD_CTX.get(provider), roles_ok=roles_for(mid, settings),
                                                status="available" if has_keys and settings.cloud_ok else "missing"))
    return list(seen.values())


class ModelRegistry:
    def __init__(self, settings: Settings, store: ModelStore, *, client: httpx.AsyncClient | None = None,
                 models_dir: Path | None = None) -> None:
        self.settings = settings
        self.store = store
        self.client = client
        env_dir = os.environ.get("OLLAMA_MODELS")
        self.models_dir = models_dir or (Path(env_dir) if env_dir else DEFAULT_OLLAMA_MODELS)
        self.ollama_up = False
        self.last_error = ""

    async def _get(self, c: httpx.AsyncClient, url: str) -> Any:
        resp = await c.get(url, timeout=3.0)
        resp.raise_for_status()
        return resp.json()

    async def _ollama(self, c: httpx.AsyncClient) -> list[ModelRow]:
        base = self.settings.ollama_base_url.rstrip("/")
        tags = await self._get(c, f"{base}/api/tags")
        try:
            ps = {m["name"]: float(m.get("size", 0)) / GB for m in (await self._get(c, f"{base}/api/ps"))["models"]}
        except (httpx.HTTPError, KeyError, ValueError):
            ps = {}
        snap = snapshot_specs()
        rows = []
        for m in tags.get("models", []):
            name = str(m["name"])
            det = m.get("details", {}) or {}
            meta: dict[str, Any] = dict(snap.get(name, {}))
            # weights not readable from here (model host, other disk): keep the rest
            with contextlib.suppress(OSError, ValueError, KeyError, StopIteration):
                meta |= gguf.architecture(gguf.read_metadata(gguf.ollama_model_file(self.models_dir, name)))
            ctx = meta.get("context_length")
            try:
                show = await c.post(f"{base}/api/show", json={"model": name}, timeout=3.0)
                info = show.json().get("model_info", {}) if show.status_code == 200 else {}
                ctx = ctx or next((v for k, v in info.items() if k.endswith(".context_length")), None)
            except (httpx.HTTPError, ValueError):
                pass
            embed = "embed" in name or "embed" in str(det.get("family", ""))
            rows.append(ModelRow(
                source="ollama", digest=str(m.get("digest", "")) or None, resident_gb=ps.get(name),
                details=meta | {"family": det.get("family"), "size_bytes": m.get("size")},
                spec=ModelSpec(id=name, family=str(det.get("family") or meta.get("architecture", "")),
                               params_b=_params_b(str(det.get("parameter_size", ""))),
                               quant=det.get("quantization_level") or meta.get("quant"), ctx=ctx, backend="ollama",
                               mem_gb=round(float(m.get("size", 0)) / GB, 2) or None,
                               roles_ok=["embed"] if embed else roles_for(name, self.settings), status="installed")))
        return rows

    async def _openai_server(self, c: httpx.AsyncClient, backend: str, url: str | None) -> list[ModelRow]:
        if not url:
            return []
        try:
            data = await self._get(c, f"{url.rstrip('/')}/models")
        except (httpx.HTTPError, ValueError):
            return []
        return [ModelRow(source=backend, spec=ModelSpec(id=f"{backend}:{m['id']}", family=str(m["id"]).split("/")[-1],
                                                        backend=backend,
                                                        roles_ok=roles_for(f"{backend}:{m['id']}", self.settings),
                                                        status="installed"))
                for m in data.get("data", [])]

    async def sync(self) -> list[ModelRow]:
        """Refresh every source; returns the merged rows (also saved)."""
        rows: list[ModelRow] = []
        own = self.client is None
        c = self.client or httpx.AsyncClient()
        try:
            try:
                rows += await self._ollama(c)
                self.ollama_up, self.last_error = True, ""
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                self.ollama_up, self.last_error = False, f"Ollama not running at {self.settings.ollama_base_url}"
                log.info("models.registry.ollama_down", error=type(exc).__name__)
                rows += from_snapshot(self.settings)
            rows += await self._openai_server(c, "mlx", self.settings.mlx_base_url)
            rows += await self._openai_server(c, "llamacpp", self.settings.llamacpp_base_url)
        finally:
            if own:
                await c.aclose()
        rows += cloud_rows(self.settings)
        if self.ollama_up:   # a model on the snapshot but no longer installed shows as missing
            have = {r.spec.id for r in rows}
            rows += [r.model_copy(update={"spec": r.spec.model_copy(update={"status": "missing"})})
                     for r in from_snapshot(self.settings) if r.spec.id not in have]
        await self.store.upsert_models(rows)
        return await self.store.list_models()

    async def installed_local(self) -> dict[str, ModelRow]:
        return {r.spec.id: r for r in await self.store.list_models()
                if r.spec.backend != "cloud" and r.spec.status in ("installed", "available")}
