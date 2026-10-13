"""Planner inputs for the gold set: Member 2's real outputs on Member 2's gold documents, made with the recorded
model answers (replay mode: no network, no keys), plus hand-written requirement sets for cases the documents lack.
Deterministic; re-run after Member 2 re-records:

    cd backend && uv run python ../samples/planning/gold/build_inputs.py

Writes ``inputs/<case>.requirement_set.json`` and ``inputs/<case>.sections.json`` (the document model trimmed to
block id -> section path, which is all the planner reads from it).
"""

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

from content import HANDWRITTEN, FROM_DOC_INTEL  # noqa: E402

from hmap.agents.doc_intel.pipeline import run_pipeline  # noqa: E402
from hmap.core.config import Settings  # noqa: E402
from hmap.core.contracts.domain import RequirementSet  # noqa: E402
from hmap.core.llm import Gateway  # noqa: E402
from tests.doc_intel.eval.run_eval import gold_cases, inputs_for  # noqa: E402


def trim(document_model: dict) -> dict:
    return {"documents": [{"doc_id": d["doc_id"], "blocks": [{"id": b["id"], "section_path": b["section_path"]}
                                                             for b in d["blocks"] if b.get("section_path")]}
                          for d in document_model["documents"]]}


async def main() -> None:
    out = HERE / "inputs"
    out.mkdir(exist_ok=True)
    llm = Gateway(Settings(llm_mode="replay")).for_plugin("doc_intel")
    for case_id, source in FROM_DOC_INTEL.items():
        case = gold_cases([source])[0]
        result = await run_pipeline(f"P-{case_id}", inputs_for(case), llm)
        rs = result.requirement_set.model_copy(update={"project_id": f"P-{case_id}", "source_docs": []})
        (out / f"{case_id}.requirement_set.json").write_text(rs.model_dump_json(indent=2) + "\n")
        (out / f"{case_id}.sections.json").write_text(
            json.dumps(trim(result.document_model.model_dump(mode="json")), indent=1) + "\n")
        print(case_id, len(rs.requirements), "requirements")
    for case_id, data in HANDWRITTEN.items():
        rs = RequirementSet.model_validate(data)
        (out / f"{case_id}.requirement_set.json").write_text(rs.model_dump_json(indent=2) + "\n")
        (out / f"{case_id}.sections.json").write_text(json.dumps({"documents": []}) + "\n")
        print(case_id, len(rs.requirements), "requirements (hand-written)")


if __name__ == "__main__":
    asyncio.run(main())
