"""Read the metadata header of a GGUF model file (item 11.1 / 11.2), from the Sprint 11 prototype
(``samples/models/gguf_meta.py``). Standard library only; the tokenizer arrays are skipped, not loaded (0.2 s).

The architecture keys (layers, KV heads, head size, context length, quantization) feed the memory model in
:mod:`hmap.agents.models.hardware`; the file size is the weight memory.
"""

import json
import struct
from pathlib import Path
from typing import Any, BinaryIO

SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S",
              12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
              32: "BF16"}
ARCH_KEYS = ("block_count", "context_length", "embedding_length", "feed_forward_length", "attention.head_count",
             "attention.head_count_kv", "attention.key_length", "attention.value_length", "full_attention_interval")


def _read(f: BinaryIO, fmt: str) -> Any:
    return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]


def _string(f: BinaryIO) -> str:
    return f.read(_read(f, "<Q")).decode("utf-8", "replace")


def _value(f: BinaryIO, kind: int) -> Any:
    if kind in SCALAR:
        return _read(f, SCALAR[kind])
    if kind == 8:
        return _string(f)
    if kind == 9:
        elem, count = _read(f, "<I"), _read(f, "<Q")
        if elem in SCALAR:
            f.seek(struct.calcsize(SCALAR[elem]) * count, 1)
            return f"<array of {count}>"
        items = [_value(f, elem) for _ in range(count)]
        return items if count <= 64 else f"<array of {count}>"
    raise ValueError(f"unknown GGUF value type {kind}")


def read_metadata(path: Path) -> dict[str, Any]:
    """Every header key, plus ``file_bytes``; architecture keys also without their ``<arch>.`` prefix."""
    with path.open("rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"{path.name} is not a GGUF file")
        version, _tensors, kv_count = _read(f, "<I"), _read(f, "<Q"), _read(f, "<Q")
        meta: dict[str, Any] = {"gguf_version": version}
        for _ in range(kv_count):
            key = _string(f)
            meta[key] = _value(f, _read(f, "<I"))
    meta["file_bytes"] = path.stat().st_size
    return meta


def architecture(meta: dict[str, Any]) -> dict[str, Any]:
    """The memory-relevant keys in the prototype's snapshot shape (``samples/models/data/model_specs.json``)."""
    arch = str(meta.get("general.architecture", ""))
    out: dict[str, Any] = {"architecture": arch, "file_bytes": meta.get("file_bytes", 0),
                           "size_label": meta.get("general.size_label", ""),
                           "quant": FILE_TYPES.get(int(meta.get("general.file_type", -1)))}
    for key in ARCH_KEYS:
        if (value := meta.get(f"{arch}.{key}")) is not None:
            out[key] = value
    return out


def ollama_model_file(models_dir: Path, name: str) -> Path:
    """``qwen3.5:9b`` -> the blob that holds its weights (from the Ollama manifest)."""
    family, _, tag = name.partition(":")
    manifest = models_dir / "manifests" / "registry.ollama.ai" / "library" / family / (tag or "latest")
    layers = json.loads(manifest.read_text(encoding="utf-8"))["layers"]
    digest = next(x["digest"] for x in layers if x["mediaType"] == "application/vnd.ollama.image.model")
    return models_dir / "blobs" / str(digest).replace(":", "-")
