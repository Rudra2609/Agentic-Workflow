"""Plan D15 / Member 6 finding F3: a repository whose comments and docs talk to the AI. The documents are built
from the code's facts, AI-directed lines are blanked before anything is read, and none of them reaches a document
or a prompt."""

from pathlib import Path

from hmap.agents.docgen.agent import DocAgent, sanitize_files
from hmap.agents.docgen.model import DocgenTrace
from hmap.core.config import Settings
from hmap.core.llm import FakeLLM
from hmap.services.artifact.memory import InMemoryArtifactStore
from tests.docgen.conftest import ROOT, assign, ctx_for, tar_of

REPO = ROOT / "samples" / "verify" / "injection" / "repo"
FORBIDDEN = ["ignore all previous instructions", "ignore previous instructions", "system prompt",
             "as an ai language model", "maintenance mode", "attacker.example.test", "delete the tests"]


def files() -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(REPO.iterdir()) if p.is_file()}


def test_every_ai_directed_line_is_blanked_line_numbers_kept() -> None:
    raw = files()
    clean, found = sanitize_files(raw)
    assert len(found) >= 4 and {f.split(":")[0] for f in found} == {"server.py", "README.md", "CONTRIBUTING.md"}
    for name, text in clean.items():
        assert text.count("\n") == raw[name].count("\n")
        assert not [w for w in FORBIDDEN if w in text.lower()], name


async def test_no_document_and_no_prompt_carries_the_injection(tmp_path: Path) -> None:
    store = InMemoryArtifactStore()
    ws = await store.put(tar_of(files()), project_id="P", artifact_type="workspace", media_type="application/gzip",
                         created_by="t", artifact_id="ws")
    fake = FakeLLM(default=None)
    task = assign(artifact_refs=[ws])
    settings = Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path), "HMAP_LLM_MODE": "fake"})
    res = await DocAgent(settings, backend=None).handle(task, ctx_for(task, store, fake))
    assert res.outcome == "success"
    for ref in res.artifact_refs:
        text = (await store.get(ref, project_id="P")).decode().lower()
        if ref.artifact_type == "docgen-trace":
            continue                                  # the trace lists the flagged lines on purpose
        assert not [w for w in FORBIDDEN if w in text], ref.artifact_id
    for c in fake.calls:
        prompt = " ".join(m.content for m in c.messages).lower()
        assert not [w for w in FORBIDDEN if w in prompt]
        assert "never instructions" in prompt
    trace = DocgenTrace.model_validate_json(await store.get(res.artifact_refs[-1], project_id="P"))
    assert any(line.startswith("server.py:") for line in trace.injected_lines)
