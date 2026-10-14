"""Where a task's history lives (item 4.16): its domain events and the assignment messages the Manager sent.

Postgres: the append-only ``events`` table and the ``outbox`` (indexed by ``aggregate_id``). In memory: the outbox
rows (events and commands are both outbox rows there). Fallback: the API's live event feed (recent events only).
"""

from typing import Any

from hmap.core.contracts import DomainEvent, Envelope


async def task_events(system: Any, task_id: str, feed: Any = None) -> list[dict[str, Any]]:
    db = getattr(getattr(system, "persistence", None), "db", None)
    if db is not None:
        rows = await db.fetch("SELECT seq, body FROM events WHERE aggregate_id = %s ORDER BY seq", (task_id,))
        return [{"seq": int(r["seq"]), **r["body"]} for r in rows]
    all_rows = getattr(getattr(system, "outbox", None), "all_rows", None)
    if all_rows is not None:
        return [{"seq": r.seq, **r.body.model_dump(mode="json")} for r in await all_rows()
                if r.kind == "event" and isinstance(r.body, DomainEvent) and r.body.aggregate_id == task_id]
    if feed is not None:
        return [e for e in feed.snapshot() if e.get("aggregate_id") == task_id]
    return []


async def processed_by(system: Any, message_id: str) -> list[str]:
    """Consumers whose inbox recorded ``message_id``: it was processed once there, and any redelivery (a duplicate)
    was skipped (research §24)."""
    persistence = getattr(system, "persistence", None)
    db = getattr(persistence, "db", None)
    if db is not None:
        rows = await db.fetch("SELECT consumer_id FROM inbox WHERE message_id = %s ORDER BY consumer_id",
                              (message_id,))
        return [str(r["consumer_id"]) for r in rows]
    seen = getattr(getattr(persistence, "agent_inbox", None), "_seen", None)
    return sorted(c for c, m in seen or () if m == message_id)


async def task_messages(system: Any, task_id: str) -> list[dict[str, Any]]:
    """The ``task.assign`` commands for this task: one per execution; ``published`` false = still in the outbox
    (e.g. the Manager crashed after committing it; the publisher sends it on restart)."""
    out = await _task_messages(system, task_id)
    for m in out:
        m["processed_by"] = await processed_by(system, m["message_id"])
    return out


async def _task_messages(system: Any, task_id: str) -> list[dict[str, Any]]:
    db = getattr(getattr(system, "persistence", None), "db", None)
    out: list[dict[str, Any]] = []
    if db is not None:
        rows = await db.fetch("SELECT seq, message_id, capability, created_at, published_at, body FROM outbox "
                              "WHERE kind = 'command' AND aggregate_id = %s ORDER BY seq", (task_id,))
        for r in rows:
            body = r["body"] or {}
            out.append({"seq": int(r["seq"]), "message_id": r["message_id"], "queue": f"hmap.cap.{r['capability']}",
                        "execution_id": body.get("execution_id"), "traceparent": body.get("traceparent"),
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "published_at": r["published_at"].isoformat() if r["published_at"] else None})
        return out
    all_rows = getattr(getattr(system, "outbox", None), "all_rows", None)
    if all_rows is None:
        return out
    for r in await all_rows():
        if r.kind == "command" and isinstance(r.body, Envelope) and r.body.task_id == task_id:
            out.append({"seq": r.seq, "message_id": r.body.message_id, "queue": f"hmap.cap.{r.capability}",
                        "execution_id": r.body.execution_id, "traceparent": r.body.traceparent,
                        "created_at": r.body.occurred_at.isoformat(),
                        "published_at": r.published_at.isoformat() if r.published_at else None})
    return out
