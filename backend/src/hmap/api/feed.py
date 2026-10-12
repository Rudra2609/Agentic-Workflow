"""Live event feed for the UI: subscribes to every domain event (``#``), keeps a bounded history (snapshot for
reconnecting clients) and fans events out to WebSocket listeners.

With Postgres the history is preloaded from the append-only ``events`` table on start (``preload_from``), so the
activity timeline survives an API restart; sequence numbers then continue after the newest stored event. Clients
also de-duplicate by ``event_id``.
"""

import asyncio
import contextlib
from collections import deque
from typing import Any

from hmap.core.bus.base import Bus, Delivery, Subscription
from hmap.core.contracts import DomainEvent


class EventFeed:
    def __init__(self, bus: Bus, *, history: int = 5000, listener_queue: int = 1000) -> None:
        self.bus = bus
        self.history: deque[dict[str, Any]] = deque(maxlen=history)
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()
        self._listener_queue = listener_queue
        self._sub: Subscription | None = None
        self._seq = 0

    async def start(self) -> None:
        self._sub = await self.bus.subscribe_events("#", self._on_event)

    async def preload_from(self, db: Any) -> int:
        """Fill the history with the newest stored events (``hmap.db.Database``); returns how many were loaded."""
        rows = await db.fetch("SELECT seq, body FROM events ORDER BY seq DESC LIMIT %s", (self.history.maxlen,))
        seen = {e.get("event_id") for e in self.history}
        items = [{"seq": int(r["seq"]), **r["body"]} for r in reversed(rows) if r["body"].get("event_id") not in seen]
        if items:
            self.history.extendleft(reversed(items))
            self._seq = max(self._seq, items[-1]["seq"])
        return len(items)

    async def stop(self) -> None:
        if self._sub is not None:
            await self._sub.cancel()
            self._sub = None

    async def _on_event(self, delivery: Delivery) -> None:
        body = delivery.body
        if isinstance(body, DomainEvent):
            self._seq += 1
            item = {"seq": self._seq, **body.model_dump(mode="json")}
            self.history.append(item)
            for q in list(self._listeners):
                with contextlib.suppress(asyncio.QueueFull):  # a slow browser drops events, never blocks the bus
                    q.put_nowait(item)
        await delivery.ack()

    def snapshot(self, *, project_id: str | None = None, after_seq: int = 0) -> list[dict[str, Any]]:
        return [e for e in self.history
                if e["seq"] > after_seq and (project_id is None or e.get("project_id") in (project_id, None))]

    def listen(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._listener_queue)
        self._listeners.add(q)
        return q

    def unlisten(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._listeners.discard(q)
