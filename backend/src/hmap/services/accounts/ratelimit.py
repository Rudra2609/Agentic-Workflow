"""Small in-process sliding-window rate limiter for login, registration and password-reset requests.

One API process serves the laptop demo, so process memory is enough; a multi-process deployment would need a shared
store (documented in HANDOFF.md).
"""

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, limit: int, window_s: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Record an attempt for ``key``; False when it is over the limit (the attempt is still counted)."""
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        hits.append(now)
        if len(self._hits) > 10_000:          # bound memory: forget idle keys
            for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window_s]:
                del self._hits[k]
        return len(hits) <= self.limit

    def retry_after(self, key: str) -> int:
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(1, int(hits[0] + self.window_s - self.clock()) + 1)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
