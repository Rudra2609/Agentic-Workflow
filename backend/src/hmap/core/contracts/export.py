"""Export JSON Schemas (draft 2020-12) for every contract.

    uv run python -m hmap.core.contracts.export [out_dir]

Writes ``messages/<type>.schema.json``, ``domain/<Name>.schema.json``, ``Envelope.schema.json`` and
``DomainEvent.schema.json`` (default ``backend/src/hmap/core/contracts/schemas``). Members code their test data
against these files; the contract tests check that every example validates.
"""

import json
import sys
from pathlib import Path
from typing import Any

from hmap.core.contracts.common import SCHEMA_VERSION, Contract
from hmap.core.contracts.domain import DOMAIN_MODELS
from hmap.core.contracts.envelope import Envelope
from hmap.core.contracts.events import DomainEvent
from hmap.core.contracts.messages import PAYLOAD_MODELS

DIALECT = "https://json-schema.org/draft/2020-12/schema"
DEFAULT_OUT = Path(__file__).with_name("schemas")


def schema_for(model: type[Contract], title: str) -> dict[str, Any]:
    schema = model.model_json_schema(mode="serialization")
    return {"$schema": DIALECT, "$id": f"hmap:{title}:{SCHEMA_VERSION}", "title": title,
            "x-schema-version": SCHEMA_VERSION, **{k: v for k, v in schema.items() if k != "title"}}


def all_schemas() -> dict[str, dict[str, Any]]:
    out = {f"messages/{t}.schema.json": schema_for(mdl, t) for t, mdl in PAYLOAD_MODELS.items()}
    out |= {f"domain/{n}.schema.json": schema_for(mdl, n) for n, mdl in DOMAIN_MODELS.items()}
    out["Envelope.schema.json"] = schema_for(Envelope, "Envelope")
    out["DomainEvent.schema.json"] = schema_for(DomainEvent, "DomainEvent")
    return out


def export(out_dir: Path = DEFAULT_OUT) -> list[Path]:
    written = []
    for rel, schema in all_schemas().items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    paths = export(target)
    print(f"wrote {len(paths)} schemas to {target}")
