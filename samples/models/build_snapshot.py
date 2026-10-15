#!/usr/bin/env python3
"""Build the data snapshot the Member 11 prototypes run on (prepared ahead of Sprint 11). Plain Python 3.11.

    python3 samples/models/build_snapshot.py [--ollama /Volumes/Tirth_SSD/ollama]

Writes ``samples/models/data/``:
- ``bakeoff_items.jsonl``: one row per (model, benchmark item) from the Sprint 11 §0 bake-off results already on
  main (``samples/model_bakeoff/results/``): score, time, JSON validity, test pass, the self-checkable signals;
- ``speed.json``: load time, tokens/s and resident memory per model (same source);
- ``model_specs.json``: architecture keys read from each local model's GGUF header (``gguf_meta.py``); only
  rebuilt when ``--ollama`` points at a models folder.

The checks (``check_memory.py``, ``check_router.py``) read only this snapshot, so they run on any laptop with no
models and no Ollama.
"""

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS = ROOT / "samples" / "model_bakeoff" / "results"
DATA = HERE / "data"
MODELS = ["qwen3.5:9b", "qwen3.5:4b", "qwen3:8b", "qwen2.5-coder:7b", "llama3.1:8b"]
SETS = ["extraction", "planning", "critique", "verify", "coding"]
KEEP = ["id", "score", "json_valid", "passed_all", "ids_ok", "acyclic", "coverage", "kind", "detected",
        "out_tokens", "in_tokens", "total_s"]


def items() -> list[dict]:
    rows = []
    for model in MODELS:
        folder = RESULTS / model.replace(":", "_")
        for name in SETS:
            for line in (folder / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    rows.append({"model": model, "set": name, **{k: r[k] for k in KEEP if k in r}})
    return rows


def specs(models_dir: Path) -> dict:
    sys.path.insert(0, str(HERE))
    from gguf_meta import FILE_TYPES, ollama_model_file, read_metadata

    out = {}
    for name in [*MODELS, "gemma4:12b", "nomic-embed-text:latest"]:
        try:
            meta = read_metadata(ollama_model_file(models_dir, name))
        except FileNotFoundError:
            continue
        arch = meta["general.architecture"]
        pick = {k.removeprefix(arch + "."): v for k, v in meta.items() if k.startswith(arch + ".")
                and not isinstance(v, str)}
        out[name] = {"architecture": arch, "size_label": meta.get("general.size_label"),
                     "quant": FILE_TYPES.get(meta.get("general.file_type"), str(meta.get("general.file_type"))),
                     "file_bytes": meta["file_bytes"], **pick}
    return out


def main() -> None:
    DATA.mkdir(exist_ok=True)
    rows = items()
    with (DATA / "bakeoff_items.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    shutil.copy(RESULTS / "speed.json", DATA / "speed.json")
    print(f"wrote {len(rows)} item rows and speed.json")
    if "--ollama" in sys.argv:
        found = specs(Path(sys.argv[sys.argv.index("--ollama") + 1]))
        (DATA / "model_specs.json").write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
        print(f"wrote specs for {len(found)} models")


if __name__ == "__main__":
    main()
