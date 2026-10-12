"""Record/replay cache (doc 02 §2.4). One JSON file per request: ``<cache_dir>/<plugin>/<key[:2]>/<key>.json``.

Cache key = SHA-256 of the canonical JSON of the *key ingredients*: plug-in name, role, the agent-supplied messages,
the output JSON Schema, temperature, max_tokens, seed and think. It deliberately EXCLUDES the gateway-injected/shared
system preamble and the resolved model name, so changing the preamble or replaying on another machine with a
different model still hits. The file stores the full request (incl. the injected preamble), the model, the response,
usage and the ``prompt_version`` (bump it to force re-recording: replay treats a different version as a miss).
"""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hmap.core.llm.base import Message
from hmap.core.llm.errors import LLMConfigError

CACHE_FORMAT = 1
_PLUGIN_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$")
_SCAN_LIMIT = 2000


def validate_plugin_name(name: str) -> str:
    """Plug-in names become a cache folder, so they must be one safe path segment."""
    if not _PLUGIN_RE.match(name) or name in (".", ".."):
        raise LLMConfigError(f"invalid plug-in name for the LLM cache: {name!r}")
    return name


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def key_ingredients(*, plugin: str, role: str, messages: Sequence[Message], schema: dict[str, Any] | None,
                    temperature: float, max_tokens: int, seed: int | None, think: bool) -> dict[str, Any]:
    """Everything that identifies a generate request — and nothing else (no preamble, no model name)."""
    return {
        "plugin": plugin,
        "role": role,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "schema": schema,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "seed": seed,
        "think": bool(think),
    }


def embed_key_ingredients(*, plugin: str, texts: Sequence[str]) -> dict[str, Any]:
    return {"plugin": plugin, "role": "embed", "texts": list(texts)}


def cache_key(ingredients: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(ingredients).encode("utf-8")).hexdigest()


def _digest(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:12]


def describe_ingredients(ingredients: dict[str, Any]) -> list[str]:
    lines = [f"  plugin      = {ingredients.get('plugin')!r}", f"  role        = {ingredients.get('role')!r}"]
    if "texts" in ingredients:
        texts = ingredients["texts"]
        lines.append(f"  texts       = {len(texts)} text(s), sha={_digest(texts)}")
        return lines
    msgs = ingredients.get("messages") or []
    lines.append(f"  messages    = {len(msgs)} agent-supplied message(s)")
    for i, m in enumerate(msgs):
        content = str(m.get("content", ""))
        preview = content[:80].replace("\n", " ") + ("..." if len(content) > 80 else "")
        lines.append(f"    [{i}] {m.get('role')}: sha={_digest(content)} {preview!r}")
    schema = ingredients.get("schema")
    schema_desc = "none" if schema is None else f"{schema.get('title', '?')} sha={_digest(schema)}"
    lines.append(f"  schema      = {schema_desc}")
    for name in ("temperature", "max_tokens", "seed", "think"):
        lines.append(f"  {name:<11} = {ingredients.get(name)!r}")
    return lines


def diff_ingredients(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Names of the ingredients that differ (messages are compared per index)."""
    out: list[str] = []
    for name in sorted(set(a) | set(b)):
        va, vb = a.get(name), b.get(name)
        if va == vb:
            continue
        if name in ("messages", "texts") and isinstance(va, list) and isinstance(vb, list):
            if len(va) != len(vb):
                out.append(f"{name} (count {len(vb)} -> {len(va)})")
            else:
                out.extend(f"{name}[{i}]" for i, (x, y) in enumerate(zip(va, vb, strict=True)) if x != y)
        else:
            out.append(name)
    return out


class ReplayCache:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path_for(self, plugin: str, key: str) -> Path:
        return self.root / validate_plugin_name(plugin) / key[:2] / f"{key}.json"

    def load(self, plugin: str, key: str) -> dict[str, Any] | None:
        path = self.path_for(plugin, key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def save(self, plugin: str, key: str, record: dict[str, Any]) -> Path:
        """Atomic write (temp file + rename) so a crash never leaves half a JSON file."""
        path = self.path_for(plugin, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": CACHE_FORMAT, "key": key, "plugin": plugin,
                   "recorded_at": datetime.now(UTC).isoformat(), **record}
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return path

    def closest(self, plugin: str, ingredients: dict[str, Any]) -> tuple[Path, list[str]] | None:
        """The recorded entry (same plug-in, same role) whose ingredients differ in the fewest places."""
        folder = self.root / validate_plugin_name(plugin)
        if not folder.is_dir():
            return None
        best: tuple[Path, list[str]] | None = None
        for i, path in enumerate(sorted(folder.glob("*/*.json"))):
            if i >= _SCAN_LIMIT:
                break
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            other = data.get("key_ingredients") if isinstance(data, dict) else None
            if not isinstance(other, dict) or other.get("role") != ingredients.get("role"):
                continue
            diff = diff_ingredients(ingredients, other)
            if best is None or len(diff) < len(best[1]):
                best = (path, diff)
        return best

    def describe_miss(self, plugin: str, key: str, ingredients: dict[str, Any], *, prompt_version: str,
                      recorded_version: str | None = None) -> str:
        path = self.path_for(plugin, key)
        if recorded_version is not None:
            head = (f"LLM replay miss: cache entry {path} was recorded with prompt_version={recorded_version!r} "
                    f"but the client asks for {prompt_version!r}; re-record with HMAP_LLM_MODE=record.")
        else:
            head = (f"LLM replay miss: no cached response at {path} (HMAP_LLM_MODE=replay). "
                    "Record it with HMAP_LLM_MODE=record, or find which ingredient changed.")
        lines = [head, f"  key         = {key}", f"  prompt_version = {prompt_version!r}",
                 *describe_ingredients(ingredients)]
        if recorded_version is None and (near := self.closest(plugin, ingredients)) is not None:
            near_path, diff = near
            lines.append(f"  closest recorded entry: {near_path} (differs in: {', '.join(diff) or 'nothing?'})")
        return "\n".join(lines)
