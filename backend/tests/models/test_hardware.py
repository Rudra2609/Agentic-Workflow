import struct
from pathlib import Path

from hmap.agents.models import gguf
from hmap.agents.models.hardware import (
    Hardware,
    feasible,
    kv_bytes_per_token,
    model_budget_gb,
    predict_gb,
    profile,
    sizing_table,
    snapshot_specs,
)

MEASURED = {"qwen3.5:9b": 5.77, "qwen3.5:4b": 3.41, "qwen3:8b": 6.63, "qwen2.5-coder:7b": 4.98, "llama3.1:8b": 5.92}


def test_memory_model_reproduces_the_prototype() -> None:
    specs = snapshot_specs()
    assert set(MEASURED) <= set(specs)
    errors = {m: predict_gb(specs[m], 8192) - gb for m, gb in MEASURED.items()}
    assert round(predict_gb(specs["qwen3.5:9b"], 8192), 2) == 5.90           # samples/models/README.md §1
    assert round(sum(abs(e) for e in errors.values()) / len(errors), 2) == 0.21
    naive = {m: abs(predict_gb(specs[m], 8192, naive=True) - gb) for m, gb in MEASURED.items()}
    assert sum(naive.values()) / len(naive) > 0.3                             # every-layer formula is worse
    # hybrid attention: only every 4th layer has a KV cache
    assert kv_bytes_per_token(specs["qwen3.5:9b"], naive=True) == 4 * kv_bytes_per_token(specs["qwen3.5:9b"])


def test_feasibility() -> None:
    specs = snapshot_specs()
    hw = Hardware(total_gb=16.0, free_gb=6.0)
    assert model_budget_gb(16.0) == 7.5
    assert feasible("qwen3.5:9b", specs["qwen3.5:9b"], hw).fit == "fits"
    loaded = Hardware(total_gb=16.0, resident={"qwen3.5:9b": 5.8, "nomic-embed-text:latest": 0.3})
    assert feasible("qwen3.5:9b", specs["qwen3.5:9b"], loaded).why == "already loaded"
    assert feasible("qwen3.5:4b", specs["qwen3.5:4b"], loaded).fit == "fits_alone"   # 9b + 4b need 24 GB
    small = Hardware(total_gb=8.0)
    assert feasible("qwen3.5:9b", specs["qwen3.5:9b"], small).fit == "does_not_fit"
    assert feasible("mystery:1b", None, hw).fit == "unknown"


def test_sizing_table_rows() -> None:
    rows = {r["ram_gb"]: r for r in sizing_table(snapshot_specs())}
    assert rows[8]["fits"] == [] and "qwen3.5:9b" in rows[16]["fits"] and set(rows) == {8, 16, 24, 48}


def test_profile_runs_here_without_ollama() -> None:
    hw = profile("http://127.0.0.1:9", docker=False)
    assert hw.total_gb > 0 and hw.ollama is False and hw.resident == {}


def _gguf(path: Path) -> None:
    def s(text: str) -> bytes:
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw

    kvs = [("general.architecture", 8, s("qwen35")), ("general.file_type", 4, struct.pack("<I", 15)),
           ("qwen35.block_count", 4, struct.pack("<I", 32)), ("qwen35.attention.head_count", 4, struct.pack("<I", 16)),
           ("qwen35.attention.head_count_kv", 4, struct.pack("<I", 4)),
           ("qwen35.full_attention_interval", 4, struct.pack("<I", 4)),
           ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 4, 3) + b"\0" * 12)]
    body = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kvs))
    for key, kind, value in kvs:
        body += s(key) + struct.pack("<I", kind) + value
    path.write_bytes(body)


def test_gguf_reader(tmp_path: Path) -> None:
    f = tmp_path / "m.gguf"
    _gguf(f)
    arch = gguf.architecture(gguf.read_metadata(f))
    assert arch["architecture"] == "qwen35" and arch["quant"] == "Q4_K_M" and arch["block_count"] == 32
    assert arch["full_attention_interval"] == 4 and arch["file_bytes"] == f.stat().st_size
    manifest = tmp_path / "manifests" / "registry.ollama.ai" / "library" / "qwen3.5" / "9b"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:x1"}]}')
    assert gguf.ollama_model_file(tmp_path, "qwen3.5:9b") == tmp_path / "blobs" / "sha256-x1"
