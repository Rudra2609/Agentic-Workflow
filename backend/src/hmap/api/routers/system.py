"""Agents, capabilities, events, dead letters, health (Sprint 1 item 1.15) + the live WebSocket.

Agents and capabilities describe the shared platform (no user data) and need only a signed-in user. Events and dead
letters belong to projects: each user receives only events of their own projects plus platform events (agents
starting/stopping, which carry no project), and dead letters only of their own projects.
"""

import asyncio
import contextlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status

from hmap.api.deps import CurrentSession, get_feed, get_system
from hmap.api.feed import EventFeed
from hmap.core.contracts.capabilities import STUBBED_CAPABILITIES
from hmap.core.runtime.discovery import capability_table
from hmap.manager.manager import Manager
from hmap.services.accounts.service import AccountService
from hmap.system import HmapSystem

router = APIRouter(tags=["system"])
SystemDep = Annotated[HmapSystem, Depends(get_system)]
FeedDep = Annotated[EventFeed, Depends(get_feed)]


class ProjectAccess:
    """Which project ids a user may see, cached per request/connection; learns new projects on demand."""

    def __init__(self, manager: Manager, user_id: str) -> None:
        self.manager, self.user_id = manager, user_id
        self._known: dict[str, bool] = {}

    async def load(self) -> "ProjectAccess":
        for p in await self.manager.list_projects(owner_id=self.user_id):
            self._known[p["project_id"]] = True
        return self

    async def allowed(self, project_id: str | None) -> bool:
        if project_id is None:
            return True                                  # platform event (agents), no user data
        if project_id not in self._known:
            rec = await self.manager.store.get_project(project_id)
            self._known[project_id] = rec is not None and rec.deleted_at is None and rec.owner_id == self.user_id
        return self._known[project_id]

    async def allowed_event(self, item: dict[str, Any]) -> bool:
        """Like :meth:`allowed`; a ``project.deleted`` event is delivered, then the project is hidden from then on."""
        ok = await self.allowed(item.get("project_id"))
        if item.get("event_type") == "project.deleted" and item.get("project_id"):
            self._known[item["project_id"]] = False
        return ok


@router.get("/health")
async def health(s: SystemDep) -> dict[str, Any]:
    """Public: lets the sign-in page show whether the server is up. Queue names/depths carry no user data."""
    return {"status": "ok", "bus": type(s.bus).__name__, "queues": await s.bus.queue_depths()}


@router.get("/agents")
async def agents(info: CurrentSession, s: SystemDep) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in await s.registry.list()]


@router.get("/agents/capabilities")
async def capabilities(info: CurrentSession, s: SystemDep) -> list[dict[str, Any]]:
    """Which plug-in serves each capability, and whether it is still a stub ("no silent stubs", Sprint 10)."""
    return [{"capability": r.capability, "status": r.status, "plugin": r.plugin, "agent": r.agent,
             "priority": r.priority} for r in capability_table(s.plugins, expected=STUBBED_CAPABILITIES)]


@router.get("/llm/usage")
async def llm_usage(info: CurrentSession, s: SystemDep) -> dict[str, Any]:
    """Gateway mode and team key-pool counters per key fingerprint (no secrets; ``{}`` without keys or in fake mode)."""
    usage = getattr(s.llm, "cloud_usage", None)
    return {"mode": getattr(s.llm, "mode", "fake"), "cloud_keys": usage() if usage is not None else {}}


@router.get("/events")
async def events(info: CurrentSession, feed: FeedDep, s: SystemDep, project_id: str | None = None,
                 after_seq: Annotated[int, Query(ge=0)] = 0,
                 limit: Annotated[int, Query(ge=1, le=2000)] = 500) -> list[dict[str, Any]]:
    """Recent events the user may see (newest ``limit``), oldest first. ``project_id`` narrows to one project."""
    access = await ProjectAccess(s.manager, info.user.user_id).load()
    if project_id is not None and not await access.allowed(project_id):
        return []
    out = [e for e in feed.snapshot(project_id=project_id, after_seq=after_seq)
           if await access.allowed(e.get("project_id"))]
    return out[-limit:]


@router.get("/dead-letters")
async def dead_letters(info: CurrentSession, s: SystemDep) -> list[dict[str, Any]]:
    """Messages that exhausted their retries, for the user's projects. Platform-level dead letters (no project)
    are listed without their body, which could contain anything."""
    access = await ProjectAccess(s.manager, info.user.user_id).load()
    out = []
    for d in await s.bus.dead_letters():
        body = d.body if isinstance(d.body, dict) else {}
        project_id = body.get("project_id") if isinstance(body.get("project_id"), str) else None
        if project_id is None:
            out.append({"queue": d.queue, "reason": d.reason, "attempts": d.attempts, "history": d.history,
                        "body": None, "project_id": None})
        elif await access.allowed(project_id):
            out.append({"queue": d.queue, "reason": d.reason, "attempts": d.attempts, "history": d.history,
                        "body": d.body, "project_id": project_id})
    return out


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket, ticket: str | None = None, after_seq: int = 0,
                    project_id: str | None = None) -> None:
    """Reconnect-safe live events. Opened with a single-use ticket from ``POST /api/auth/ws-ticket`` (checked
    before accepting); sends the missed history (``after_seq``) first, then streams — only events the user may see."""
    allowed_origins = set(ws.app.state.allowed_origins)
    origin = ws.headers.get("origin")
    accounts: AccountService = ws.app.state.accounts
    user_id = accounts.redeem_ticket(ticket)
    if (origin is not None and origin not in allowed_origins) or user_id is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    feed: EventFeed = ws.app.state.feed
    system: HmapSystem = ws.app.state.system
    access = await ProjectAccess(system.manager, user_id).load()
    if project_id is not None and not await access.allowed(project_id):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()
    q = feed.listen()
    try:
        last = after_seq
        for item in feed.snapshot(project_id=project_id, after_seq=after_seq):
            if await access.allowed_event(item):
                await ws.send_json(item)
            last = item["seq"]
        while True:
            item = await q.get()
            if item["seq"] <= last or (project_id and item.get("project_id") not in (project_id, None)):
                continue
            last = item["seq"]
            if await access.allowed_event(item):
                await ws.send_json(item)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        feed.unlisten(q)
        with contextlib.suppress(Exception):
            await ws.close()
