"""Items 9.3-9.5, 9.7, 9.8: summaries with citations, facts-first README / API / architecture (grounded by
construction), OpenAPI -> routes, the example verifier on the local sandbox, report sections in both modes."""

from datetime import UTC, datetime

import pytest

from hmap.agents.docgen import api_docs, architecture, examples, readme, report
from hmap.agents.docgen import summarize as S
from hmap.agents.docgen.grounding import rule_claims
from hmap.agents.testing.sandbox import choose
from hmap.core.config import Settings
from hmap.core.contracts import RequirementSet
from hmap.core.contracts.domain import ResearchReport, VerificationReport
from hmap.core.llm import FakeLLM
from tests.docgen.conftest import REPO_NAMES, repo_facts, repo_files


@pytest.mark.parametrize("name", REPO_NAMES)
async def test_facts_first_documents_are_fully_grounded(name: str) -> None:
    f, files = repo_facts(name), repo_files(name)
    arch = architecture.extract(f)
    summ = await S.summarize(f, files, None, arch=arch)
    docs = {"readme": readme.render(f, arch, summ, S.facts_overview(f, arch)), "api": api_docs.render(f),
            "architecture": architecture.render_doc(f, arch, architecture.details(f, arch), "x"),
            "summaries": S.render(summ, f)}
    for doc, md in docs.items():
        claims = rule_claims(md, f, doc)
        assert claims or (doc == "api" and not f.routes), doc
        assert [c for c in claims if c.verdict == "ungrounded"] == [], doc


@pytest.mark.parametrize("name", REPO_NAMES)
def test_api_endpoints_equal_code_endpoints(name: str) -> None:
    f = repo_facts(name)
    md = api_docs.render(f)
    documented = {c.text for c in rule_claims(md, f) if c.kind == "ENDPOINT"}
    assert documented == {f"{r.method} {r.path}" for r in f.routes}


async def test_summaries_cite_real_symbols_and_reuse_the_cache() -> None:
    f, files = repo_facts("todo_api"), repo_files("todo_api")
    fake = FakeLLM(default=None)
    fake.on_schema(S._SymAnswers, S._SymAnswers(summaries=[S._SymAnswer(symbol="add_todo", summary="Inserts a todo.")]))
    answer = S._FileAnswer(path="storage.py", summary="SQLite storage, see `storage.py::add_todo`.")
    fake.on_schema(S._FileAnswers, S._FileAnswers(files=[answer]))
    fake.on_schema(S._RepoAnswer, S._RepoAnswer(summary="A todo API (`app.py::create`, `app.py::invented`)."))
    out = await S.summarize(f, files, fake, limit=60)
    assert any(s.name == "add_todo" and s.by == "model" for s in out.symbols)
    assert out.file_by["storage.py"] == "docstring"                     # a docstring beats the model
    assert "app.py::invented" in out.removed and "`app.py::create`" in out.repo and "invented" in out.repo
    calls = len(fake.calls)
    again = await S.summarize(f, files, FakeLLM(default=None), limit=60, previous=out)
    assert any(s.name == "add_todo" and s.by == "model" for s in again.symbols)     # cached by file hash
    assert calls >= 3


async def test_summary_limit_and_no_model() -> None:
    f, files = repo_facts("todo_api"), repo_files("todo_api")
    out = await S.summarize(f, files, None, limit=0)
    assert out.note and out.repo_by == "facts"
    assert all(s.by in ("docstring", "signature") for s in out.symbols)
    assert out.public_symbols == len([1 for _, s in f.public_symbols()])


def test_openapi_to_routes() -> None:
    spec = {"paths": {"/api/items/{item_id}": {"get": {"operationId": "read_api_items__item_id__get",
                                                       "parameters": [{"name": "item_id", "in": "path",
                                                                       "schema": {"type": "integer"}}],
                                                       "responses": {"200": {"content": {"application/json": {
                                                           "schema": {"$ref": "#/components/schemas/Item"}}}}}}}}}
    known = repo_facts("todo_api").routes
    routes = api_docs.routes_from_openapi(spec, known)
    assert routes[0].path == "/api/items/{item_id}" and routes[0].response_model == "Item"
    assert routes[0].params == ["item_id: integer (path)"] and routes[0].source == "openapi"
    assert routes[0].file == "app.py" and routes[0].function == "read"


@pytest.fixture
async def local_backend(settings: Settings):  # type: ignore[no-untyped-def]
    return await choose(settings)


async def test_examples_run_check_and_skip(local_backend) -> None:  # type: ignore[no-untyped-def]
    f, files = repo_facts("tcp_chat"), repo_files("tcp_chat")
    md = ("# x\n\n```python\nfrom protocol import frame\nprint(frame('hi'))\n```\n\n```python\nimport protocol\n"
          "protocol.no_such_function()\n```\n\n```bash\npip install -r requirements.txt\npython server.py\n"
          "rm -rf /\npytest\npytest\n```\n")
    out = await examples.verify({"readme": md}, f, files, local_backend)
    by = {(e.code.strip().splitlines()[-1], e.action): e for e in out}
    assert by[("print(frame('hi'))", "run")].ok is True
    assert by[("protocol.no_such_function()", "run")].ok is False
    assert by[("pip install -r requirements.txt", "check")].ok is None
    assert by[("python server.py", "check")].ok is None
    assert by[("rm -rf /", "skip")].ok is None
    tests = [e for e in out if e.code == "pytest"]
    assert len(tests) == 2 and all(e.ok for e in tests)          # run once, reported twice


async def test_examples_without_a_sandbox_are_skipped() -> None:
    out = await examples.verify({"r": "```python\nprint(1)\n```\n"}, repo_facts("tcp_chat"), {}, None)
    assert out[0].action == "skip" and "no sandbox" in out[0].why


def _rs() -> RequirementSet:
    return RequirementSet.model_validate({
        "project_id": "P", "requirements": [
            {"id": "R1", "text": "Clients can add a todo item and list all todo items", "source_ref": {"doc_id": "d"}},
            {"id": "R2", "text": "Export the data to a spreadsheet in XLSX format", "source_ref": {"doc_id": "d"}},
            {"id": "R3", "text": "The API listens on port 9000", "source_ref": {"doc_id": "d"}}],
        "deliverables": [{"id": "D1", "name": "Project report", "format": "PDF"},
                         {"id": "D2", "name": "Source code ZIP"}]})


def test_report_sections_software() -> None:
    f = repo_facts("todo_api")
    arch = architecture.extract(f)
    out = report.software(f, arch, None, _rs(), {"passed": False, "stages": {"unit": {"status": "failed"}},
                                                 "failures": [{"message": "assert 1 == 2"}]}, "Project report")
    assert report.doc_deliverables(_rs()) == ["Project report"]
    assert out.markdown.startswith("# Project report")
    rows = {r["req_id"]: r for r in out.coverage}
    assert rows["R1"]["status"] == "shown" and rows["R2"]["status"] == "not shown"
    assert rows["R3"]["status"] == "conflict" and "R3: the code uses port 8000, not 9000." in out.markdown
    assert "R2: not shown in the code yet." in out.markdown and "The tests do not all pass yet" in out.markdown
    assert [c for c in rule_claims(out.markdown, f, "report") if c.verdict == "ungrounded"] == []


def _research() -> tuple[ResearchReport, VerificationReport]:
    now = datetime.now(UTC).isoformat()
    ev = [{"id": f"E{i}", "url": f"https://example.test/{i}", "quote": "q", "content_sha256": "a" * 64,
           "retrieved_at": now} for i in (1, 2)]
    rr = ResearchReport.model_validate({"task_id": "R", "claims": [
        {"id": "C1", "text": "TCP guarantees in-order delivery of bytes", "evidence_ids": ["E1"]},
        {"id": "C2", "text": "UDP is always faster for chat clients", "evidence_ids": ["E2"]}],
        "evidence": ev, "stop_reason": "done"})
    vr = VerificationReport.model_validate({"task_id": "V", "claim_verdicts": [
        {"claim_id": "C1", "verdict": "VERIFIED", "confidence": 0.9},
        {"claim_id": "C2", "verdict": "UNSUPPORTED", "confidence": 0.8}]})
    return rr, vr


async def test_document_mode_uses_only_verified_claims() -> None:
    rr, vr = _research()
    rs = RequirementSet.model_validate({"project_id": "P", "requirements": [
        {"id": "R1", "text": "Explain how TCP delivers bytes in order", "source_ref": {"doc_id": "d"}}],
        "deliverables": [{"id": "D1", "name": "Essay", "format": "PDF"}]})
    out = await report.document(None, rs, rr, vr, "Write the essay", "document", "Essay")
    assert "in-order delivery" in out.markdown and "UDP" not in out.markdown
    assert "https://example.test/1" in out.markdown and "https://example.test/2" not in out.markdown
    assert all(c.verdict == "grounded" for c in out.claims)
    outline = await report.document(None, rs, rr, vr, "Outline", "design", "Essay")
    assert "Outline:" in outline.markdown and "[C1]" in outline.markdown


async def test_document_mode_removes_uncited_model_sentences() -> None:
    rr, vr = _research()
    rs = RequirementSet.model_validate({"project_id": "P", "requirements": [
        {"id": "R1", "text": "Explain how TCP delivers bytes in order", "source_ref": {"doc_id": "d"}}]})
    fake = FakeLLM(default=None).on_schema(report._Paragraph, report._Paragraph(
        text="TCP keeps bytes in order [C1]. It was invented in 1999 by Redis Labs. UDP wins [C2]."))
    out = await report.document(fake, rs, rr, vr, "Write", "document", "Report")
    assert "TCP keeps bytes in order [C1]." in out.markdown
    assert "1999" not in out.markdown and "UDP wins" not in out.markdown
    bad = [c for c in out.claims if c.verdict == "ungrounded"]
    assert len(bad) == 2
