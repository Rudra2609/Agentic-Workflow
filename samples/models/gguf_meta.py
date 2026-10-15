#!/usr/bin/env python3
"""Read the metadata header of a GGUF model file (Member 11, prepared ahead of Sprint 11 items 11.1 / 11.2). Plain
Python 3.11: no llama.cpp, no Ollama running. Large arrays (the tokenizer vocabulary) are skipped, not loaded.

    python3 samples/models/gguf_meta.py /path/to/model.gguf                     # architecture keys as JSON
    python3 samples/models/gguf_meta.py --ollama /path/to/ollama/models qwen3.5:9b

The architecture keys (layers, KV heads, head size, context length, quantization) are what the memory calculator in
``memory.py`` needs; the file size is the weight memory.
"""

import json
import struct
import sys
from pathlib import Path

SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S",
              12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
              32: "BF16"}


def _read(f, fmt: str):
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, f.read(size))[0]


def _string(f) -> str:
    return f.read(_read(f, "<Q")).decode("utf-8", "replace")


def _value(f, kind: int, keep_arrays: bool):
    if kind in SCALAR:
        return _read(f, SCALAR[kind])
    if kind == 8:
        return _string(f)
    if kind == 9:
        elem, count = _read(f, "<I"), _read(f, "<Q")
        if elem in SCALAR and not keep_arrays:
            f.seek(struct.calcsize(SCALAR[elem]) * count, 1)
            return f"<array of {count}>"
        items = [_value(f, elem, keep_arrays) for _ in range(count)]
        return items if keep_arrays or count <= 64 else f"<array of {count}>"
    raise ValueError(f"unknown GGUF value type {kind}")


def read_metadata(path: Path) -> dict:
    with path.open("rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"{path} is not a GGUF file")
        version, _tensors, kv_count = _read(f, "<I"), _read(f, "<Q"), _read(f, "<Q")
        meta = {"gguf_version": version}
        for _ in range(kv_count):
            key = _string(f)
            meta[key] = _value(f, _read(f, "<I"), keep_arrays=False)
    meta["file_bytes"] = path.stat().st_size
    return meta


def ollama_model_file(models_dir: Path, name: str) -> Path:
    """``qwen3.5:9b`` -> the blob that holds its model.gguf (from the Ollama manifest)."""
    family, _, tag = name.partition(":")
    manifest = models_dir / "manifests" / "registry.ollama.ai" / "library" / family / (tag or "latest")
    layers = json.loads(manifest.read_text(encoding="utf-8"))["layers"]
    digest = next(x["digest"] for x in layers if x["mediaType"] == "application/vnd.ollama.image.model")
    return models_dir / "blobs" / digest.replace(":", "-")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    target = ollama_model_file(Path(sys.argv[2]), sys.argv[3]) if sys.argv[1] == "--ollama" else Path(sys.argv[1])
    meta = read_metadata(target)
    print(json.dumps({k: v for k, v in meta.items() if not k.startswith("tokenizer.")}, indent=1))
