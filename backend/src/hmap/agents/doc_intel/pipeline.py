"""The document-intelligence pipeline (spec §4), independent of the bus so the agent, the tests and the eval harness
all run the same code:

    load (+OCR) -> structure -> tables -> chunks -> rules + LLM per chunk -> merge -> validate -> RequirementSet
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from hmap.agents.doc_intel.cache import ResultCache
from hmap.agents.doc_intel.chunking import DEFAULT_BUDGET_TOKENS, make_chunks
from hmap.agents.doc_intel.extract.llm import PROMPT_VERSION, ChunkExtraction, extract_chunk
from hmap.agents.doc_intel.extract.quotes import locate
from hmap.agents.doc_intel.extract.rules import MODAL_RE, RuleHit, rule_pass
from hmap.agents.doc_intel.loaders import InputDocument, load_document
from hmap.agents.doc_intel.merge import (
    CONF_APPROXIMATE,
    CONF_EXACT,
    CONF_RULE_AGREES,
    CONF_RULES_ONLY,
    CONF_TABLE,
    CONF_UNVERIFIED,
    Candidate,
    assemble,
)
from hmap.agents.doc_intel.model import DocumentModel, ExtractionInfo, SourceDocument
from hmap.agents.doc_intel.ocr import OcrEngine
from hmap.agents.doc_intel.structure import build_document
from hmap.agents.doc_intel.tables import read_table, stated_total
from hmap.agents.doc_intel.validate import check
from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.domain import RequirementSet
from hmap.core.errors import Cancelled, HmapError
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.doc_intel")

ProgressFn = Callable[[int, str], Awaitable[None]]
KIND = {"requirement": "R", "constraint": "C", "deliverable": "D"}
MAX_QUESTIONS = 12


@dataclass
class PipelineStats:
    documents: int = 0
    pages: int = 0
    ocr_pages: int = 0
    chunks: int = 0
    llm_chunks: int = 0
    rules_only_chunks: int = 0
    quotes: dict[str, int] = field(default_factory=lambda: {"exact": 0, "approximate": 0, "unverified": 0})
    issues: list[str] = field(default_factory=list)
    answered_by: dict[str, int] = field(default_factory=dict)


@dataclass
class PipelineResult:
    requirement_set: RequirementSet
    document_model: DocumentModel
    stats: PipelineStats


def _table_candidates(doc_index: int, doc: SourceDocument) -> list[Candidate]:
    out: list[Candidate] = []
    for table in doc.tables:
        reading = read_table(table.rows)
        block = doc.block(table.block_id)
        for row in reading.criteria:
            out.append(Candidate("E", row.criterion, doc_index, doc, block=block, quote=row.criterion,
                                 char_span=(block.char_start, block.char_end) if block else None,
                                 confidence=CONF_TABLE, origin="table", max_marks=row.max_marks, levels=row.levels))
        for name, fmt in reading.deliverables:
            out.append(Candidate("D", name, doc_index, doc, block=block, quote=name, confidence=CONF_TABLE,
                                 origin="table", name=name, fmt=fmt,
                                 char_span=(block.char_start, block.char_end) if block else None))
    return out


def _doc_total(doc: SourceDocument) -> float | None:
    prose = "\n".join(b.text for b in doc.blocks if b.type not in ("table", "header", "footer", "note"))
    total = stated_total(prose)
    if total is None:
        for table in doc.tables:
            total = read_table(table.rows).total
            if total is not None:
                break
    return total


def _rule_candidates(hits: list[RuleHit], docs: list[SourceDocument]) -> list[Candidate]:
    out: list[Candidate] = []
    for h in hits:
        doc = docs[h.doc_index]
        block = doc.block(h.block_id)
        match = locate(h.text, [block] if block else [])
        out.append(Candidate(h.kind, h.text, h.doc_index, doc, block=block, quote=h.text, char_span=match.char_span,
                             confidence=CONF_RULES_ONLY, origin="rules", priority=h.priority, ckind=h.ckind,
                             name=h.text if h.kind == "D" else ""))
    return out


async def run_pipeline(project_id: str, inputs: list[InputDocument], llm: LLMClient | None, *,
                       source_refs: list[ArtifactRef] | None = None, cache: ResultCache | None = None,
                       progress: ProgressFn | None = None, check_cancelled: Callable[[], None] | None = None,
                       use_llm: bool = True, budget: int = DEFAULT_BUDGET_TOKENS) -> PipelineResult:
    async def report(percent: int, summary: str) -> None:
        if check_cancelled is not None:
            check_cancelled()
        if progress is not None:
            await progress(percent, summary)

    stats = PipelineStats(documents=len(inputs))
    ocr = OcrEngine(llm if use_llm else None, cache)
    docs: list[SourceDocument] = []
    for i, doc in enumerate(inputs):
        label = f"{doc.folder}/{doc.name}" if doc.folder else doc.name

        async def on_page(done: int, total: int, label: str = label, i: int = i) -> None:
            span = 40 / max(1, len(inputs))
            await report(int(5 + span * i + span * done / max(1, total)), f"Reading {label}: page {done} of {total}")

        await report(int(5 + 40 * i / max(1, len(inputs))), f"Reading {label}")
        loaded = await load_document(doc, ocr, on_page)
        docs.append(build_document(doc, loaded))
    stats.pages = sum(len(d.pages) or 1 for d in docs)
    stats.ocr_pages = sum(1 for d in docs for p in d.pages if p.ocr)

    candidates: list[Candidate] = [c for i, d in enumerate(docs) for c in _table_candidates(i, d)]
    hits = rule_pass(docs)
    chunks = make_chunks(docs, budget)
    stats.chunks = len(chunks)
    questions: list[str] = []
    for n, chunk in enumerate(chunks, start=1):
        await report(45 + int(45 * (n - 1) / max(1, len(chunks))),
                     f"Extracting requirements: part {n} of {len(chunks)}")
        block_ids = {b.id for b in chunk.blocks}
        chunk_hits = [h for h in hits if h.doc_index == chunk.doc_index and h.block_id in block_ids]
        extraction: ChunkExtraction | None = None
        if use_llm and llm is not None:
            try:
                extraction, who = await extract_chunk(llm, chunk, chunk_hits, cache)
                stats.answered_by[who] = stats.answered_by.get(who, 0) + 1
            except Cancelled:
                raise
            except (HmapError, httpx.HTTPError) as exc:  # model down or answered garbage: keep going on rules
                log.warning("doc_intel.extract.chunk_failed", chunk=chunk.index, error=type(exc).__name__)
        if extraction is not None and not extraction.items and chunk_hits:
            # an empty answer where the keyword rules found candidates is a miss, not "nothing to extract"
            log.warning("doc_intel.extract.empty_answer", chunk=chunk.index, rule_hits=len(chunk_hits))
            questions += extraction.open_questions
            extraction = None
        if extraction is None:
            stats.rules_only_chunks += 1
            candidates += _rule_candidates(chunk_hits, docs)
            continue
        stats.llm_chunks += 1
        questions += extraction.open_questions
        for item in extraction.items:
            if item.text.strip().endswith(":"):  # a lead-in that introduces a list is never an item itself
                continue
            match = locate(item.quote, chunk.blocks, item.text)
            stats.quotes[match.status] += 1
            conf = {"exact": CONF_EXACT, "approximate": CONF_APPROXIMATE}.get(match.status, CONF_UNVERIFIED)
            kind = KIND[item.kind]
            priority: str = item.priority
            agreeing = [h for h in chunk_hits if match.block is not None and h.block_id == match.block.id
                        and h.kind == kind]
            if agreeing:
                conf += CONF_RULE_AGREES
                # an explicit must / should / may in the source sentence (or its list lead-in) decides the priority;
                # models tend to turn "should" into "must"
                worded = [h for h in agreeing if MODAL_RE.search(h.text)]
                if worded and kind == "R":
                    priority = worded[0].priority
            cand = Candidate(kind, item.text.strip() or item.quote.strip(), chunk.doc_index, chunk.document,
                             block=match.block, quote=item.quote.strip() if match.status != "unverified" else None,
                             char_span=match.char_span, confidence=conf, priority=priority,
                             rtype=item.req_type, ckind=item.constraint_kind,
                             name=item.deliverable_name or item.text, fmt=item.deliverable_format)
            candidates.append(cand)
            if match.status == "unverified" and kind == "R":
                questions.append(f"Please check the requirement \"{cand.text}\": its source was not found in "
                                 f"{chunk.document.name}.")

    await report(92, "Merging and checking the requirements")
    assembled = assemble(candidates)
    totals = [t for t in (_doc_total(d) for d in docs) if t is not None]
    criteria_sum = sum(e.max_marks for e in assembled.evaluation_criteria)
    consistent = bool(totals) and abs(sum(totals) - criteria_sum) < 0.01 and bool(assembled.evaluation_criteria)
    if stats.rules_only_chunks:
        questions.append("The language model did not answer for part of the documents, so some items were found by "
                         "keyword rules only. Please review them.")
    for d in docs:
        for warning in d.warnings:
            questions.append(f"{d.name}: {warning}.")
    rs = RequirementSet(project_id=project_id, source_docs=source_refs or [], requirements=assembled.requirements,
                        constraints=assembled.constraints, deliverables=assembled.deliverables,
                        evaluation_criteria=assembled.evaluation_criteria,
                        total_marks=sum(totals) if consistent or (totals and not assembled.evaluation_criteria)
                        else None)
    validation = check(rs, totals)
    stats.issues = validation.issues
    questions += validation.questions
    unique: list[str] = []
    for q in (q.strip() for q in questions):
        if q and q.lower() not in {u.lower() for u in unique}:
            unique.append(q)
    rs = rs.model_copy(update={"open_questions": unique[:MAX_QUESTIONS]})
    RequirementSet.model_validate(rs.model_dump())  # the contract (ids, marks sum) still holds after the update
    await report(98, f"Found {len(rs.requirements)} requirements, {len(rs.constraints)} constraints, "
                     f"{len(rs.deliverables)} deliverables and {len(rs.evaluation_criteria)} marking criteria")
    ocr_pages: dict[str, int] = {}
    for d in docs:
        for page in d.pages:
            if page.ocr:
                engine = page.ocr_engine or "none"
                ocr_pages[engine] = ocr_pages.get(engine, 0) + 1
    info = ExtractionInfo(chunks=stats.chunks, llm_chunks=stats.llm_chunks, rules_only_chunks=stats.rules_only_chunks,
                          answered_by=stats.answered_by, quotes=stats.quotes, ocr_pages=ocr_pages,
                          prompt_version=PROMPT_VERSION)
    return PipelineResult(rs, DocumentModel(project_id=project_id, documents=docs, extraction=info), stats)
