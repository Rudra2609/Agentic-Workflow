"""A cache whose entries expire after a timeout in seconds."""

import time


class TTLCache:
    def __init__(self, timeout_seconds: float = 60) -> None:
        self.timeout = timeout_seconds
        self.items: dict[str, tuple[float, object]] = {}

    def get(self, key: str) -> object | None:
        hit = self.items.get(key)
        if hit is None or time.time() - hit[0] > self.timeout:
            return None
        return hit[1]

    def put(self, key: str, value: object) -> None:
        self.items[key] = (time.time(), value)
