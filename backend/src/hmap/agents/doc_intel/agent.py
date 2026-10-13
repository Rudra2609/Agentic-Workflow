"""``DocIntelAgent`` (spec item 2.8): the real ``document.extract`` capability. The Sprint-1 stub stands down
automatically because this plug-in has a higher priority.

Input: the uploaded documents as artifact refs, plus ``inputs["documents"]`` = ``[{artifact_id, name, folder, path}]``
(absent for a typed request). Output: a ``requirement-set`` artifact (the contract for Member 3) and a
``document-model`` artifact (the parsed documents, for the source view in the UI).
"""

from collections import OrderedDict
from typing import Any, ClassVar

from hmap.agents.doc_intel.loaders import InputDocument
from hmap.agents.doc_intel.pipeline import run_pipeline
from hmap.core.contracts import TaskAssign, TaskResult
from hmap.core.contracts.capabilities import DOCUMENT_EXTRACT
from hmap.core.errors import ErrorCode, HmapError
from hmap.core.runtime.base import AgentContext, BaseAgent

MEDIA_EXT = {"application/pdf": ".pdf", "text/plain": ".txt", "text/markdown": ".md", "image/png": ".png",
             "image/jpeg": ".jpg",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"}


class LruCache:
    """Bounded in-process cache (vision OCR per page, LLM extraction per chunk). Kept in memory on purpose: entries
    hold document text, which must not outlive a deleted project on disk. Covers redelivery and "Run again" while
    the agent process lives; the replay cache covers tests and demos."""

    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max_entries
        self._data: OrderedDict[str, str] = OrderedDict()

    async def get(self, key: str) -> str | None:
        value = self._data.get(key)
        if value is not None:
            self._data.move_to_end(key)
        return value

    async def put(self, key: str, value: str) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)


class _ProjectCache:
    """One shared LRU, namespaced per project."""

    def __init__(self, shared: LruCache, project_id: str) -> None:
        self.shared, self.prefix = shared, f"{project_id}:"

    async def get(self, key: str) -> str | None:
        return await self.shared.get(self.prefix + key)

    async def put(self, key: str, value: str) -> None:
        await self.shared.put(self.prefix + key, value)


def document_name(ref_id: str, media_type: str, meta: dict[str, Any], *, only_one: bool, index: int) -> str:
    if meta.get("name"):
        return str(meta["name"])
    if only_one and media_type == "text/plain":
        return "request.txt"  # a typed request is stored as one text document
    return f"document-{index}{MEDIA_EXT.get(media_type, '')}"


class DocIntelAgent(BaseAgent):
    name = "doc-intel"
    capabilities = (DOCUMENT_EXTRACT,)
    max_slots = 1             # OCR and the model run one after the other (spec §6: memory)
    version = "2.0"
    cache: ClassVar[LruCache] = LruCache()

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        refs = [r for r in task.artifact_refs if r.artifact_type == "document"] or list(task.artifact_refs)
        if not refs:
            raise HmapError("document.extract needs at least one uploaded document", code=ErrorCode.INVALID_TASK,
                            retryable=False)
        meta = {d.get("artifact_id"): d for d in (task.inputs or {}).get("documents") or [] if isinstance(d, dict)}
        await ctx.progress(2, f"Opening {len(refs)} document{'s' if len(refs) != 1 else ''}")
        inputs: list[InputDocument] = []
        for i, ref in enumerate(refs, start=1):
            info = meta.get(ref.artifact_id, {})
            inputs.append(InputDocument(
                doc_id=ref.artifact_id, data=await ctx.artifacts.get(ref, project_id=ctx.project_id),
                name=document_name(ref.artifact_id, ref.media_type, info, only_one=len(refs) == 1, index=i),
                media_type=ref.media_type, folder=info.get("folder") or None, path=info.get("path") or None))
        result = await run_pipeline(ctx.project_id, inputs, ctx.llm, source_refs=refs,
                                    cache=_ProjectCache(self.cache, ctx.project_id), progress=ctx.progress,
                                    check_cancelled=ctx.check_cancelled)
        rs, stats = result.requirement_set, result.stats
        rs_ref = await ctx.put_json(rs, artifact_type="requirement-set")
        dm_ref = await ctx.put_json(result.document_model, artifact_type="document-model")
        await ctx.progress(100, "Requirements ready")
        summary = (f"{len(rs.requirements)} requirements, {len(rs.constraints)} constraints, "
                   f"{len(rs.deliverables)} deliverables, {len(rs.evaluation_criteria)} marking criteria"
                   + (f"; {len(rs.open_questions)} open questions" if rs.open_questions else ""))
        evidence = [f"pages={stats.pages}", f"ocr_pages={stats.ocr_pages}", f"chunks={stats.chunks}",
                    f"llm_chunks={stats.llm_chunks}", f"rules_only_chunks={stats.rules_only_chunks}",
                    f"quotes_exact={stats.quotes['exact']}", f"quotes_unverified={stats.quotes['unverified']}"]
        return ctx.result([rs_ref, dm_ref], summary=summary, evidence=evidence)
