"""API (spec item 2.10), mounted at ``/api/doc_intel``. Every route checks project ownership (404 for anyone else's
project, like the core API).

- ``GET  /requirements/{project_id}[?artifact_id=&version=]``  the latest (or a given) RequirementSet + its versions
- ``PUT  /requirements/{project_id}``                          a human edit -> a new version of the same artifact
- ``GET  /document-model/{project_id}``                        the parsed documents (blocks, pages, tables)
- ``GET  /pages/{project_id}/{artifact_id}/{n}``               page ``n`` of an uploaded document as a PNG
"""

import asyncio
import io
from typing import Annotated, Any

import pypdfium2 as pdfium
from fastapi import APIRouter, HTTPException, Query, Response, status
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.domain import RequirementSet

router = APIRouter()

PAGE_DPI = 110
MAX_PAGE_PIXELS = 2400


class RequirementsEdit(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=200)
    base_version: int = Field(ge=1, description="the version the edit started from (stale edits are refused)")
    requirement_set: dict[str, Any]


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


async def _refs(m: Any, project_id: str, artifact_type: str) -> list[ArtifactRef]:
    return [r for r in await m.artifacts.list(project_id) if r.artifact_type == artifact_type]


def _pick(refs: list[ArtifactRef], artifact_id: str | None, version: int | None) -> tuple[ArtifactRef | None,
                                                                                         list[ArtifactRef]]:
    if not refs:
        return None, []
    if artifact_id is None:  # the newest extraction (each run makes a new artifact; edits add versions to it)
        firsts = [r for r in refs if r.version == 1] or refs
        artifact_id = max(firsts, key=lambda r: r.created_at).artifact_id
    versions = sorted((r for r in refs if r.artifact_id == artifact_id), key=lambda r: r.version)
    if not versions:
        return None, []
    if version is None:
        return versions[-1], versions
    return next((r for r in versions if r.version == version), None), versions


@router.get("/requirements/{project_id}")
async def get_requirements(project_id: str, info: CurrentSession, m: ManagerDep,
                           artifact_id: str | None = None,
                           version: Annotated[int | None, Query(ge=1)] = None) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    ref, versions = _pick(await _refs(m, project_id, "requirement-set"), artifact_id, version)
    if ref is None:
        raise _not_found("Requirements")
    rs = RequirementSet.model_validate_json(await m.artifacts.get(ref, project_id=project_id))
    return {"artifact": ref.model_dump(mode="json"), "requirement_set": rs.model_dump(mode="json"),
            "versions": [{"version": r.version, "created_by": r.created_by, "created_at": r.created_at.isoformat()}
                         for r in versions]}


@router.put("/requirements/{project_id}")
async def edit_requirements(project_id: str, body: RequirementsEdit, info: CurrentSession,
                            m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    ref, versions = _pick(await _refs(m, project_id, "requirement-set"), body.artifact_id, None)
    if ref is None:
        raise _not_found("Requirements")
    if ref.version != body.base_version:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"These requirements were changed meanwhile (now "
                                                             f"version {ref.version}). Reload and try again.")
    try:
        rs = RequirementSet.model_validate({**body.requirement_set, "project_id": project_id})
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Not saved: {first.get('msg', 'invalid')}" + (f" ({where})" if where else ""),
                            ) from None
    new = await m.artifacts.put(rs.model_dump_json(indent=2).encode(), project_id=project_id,
                                artifact_type="requirement-set", media_type="application/json",
                                created_by=f"user:{info.user.user_id}", artifact_id=body.artifact_id)
    return {"artifact": new.model_dump(mode="json"), "requirement_set": rs.model_dump(mode="json"),
            "versions": [{"version": r.version, "created_by": r.created_by, "created_at": r.created_at.isoformat()}
                         for r in [*versions, new]]}


@router.get("/document-model/{project_id}")
async def get_document_model(project_id: str, info: CurrentSession, m: ManagerDep) -> Response:
    await owned_project(project_id, info, m)
    ref, _ = _pick(await _refs(m, project_id, "document-model"), None, None)
    if ref is None:
        raise _not_found("Document model")
    return Response(await m.artifacts.get(ref, project_id=project_id), media_type="application/json")


def _render(data: bytes, media_type: str, page: int) -> bytes | None:
    if data[:4] == b"%PDF" or media_type == "application/pdf":
        pdf = pdfium.PdfDocument(data)
        try:
            if page < 1 or page > len(pdf):
                return None
            image = pdf[page - 1].render(scale=PAGE_DPI / 72).to_pil()
        finally:
            pdf.close()
    elif media_type.startswith("image/") and page == 1:
        image = Image.open(io.BytesIO(data))
    else:
        return None
    image.thumbnail((MAX_PAGE_PIXELS, MAX_PAGE_PIXELS))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


@router.get("/pages/{project_id}/{artifact_id}/{page}")
async def page_image(project_id: str, artifact_id: str, page: int, info: CurrentSession, m: ManagerDep) -> Response:
    await owned_project(project_id, info, m)
    ref, _ = _pick(await _refs(m, project_id, "document"), artifact_id, None)
    if ref is None:
        raise _not_found("Document")
    png = await asyncio.to_thread(_render, await m.artifacts.get(ref, project_id=project_id), ref.media_type, page)
    if png is None:
        raise _not_found("Page")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600",
                                                          "X-Content-Type-Options": "nosniff"})
