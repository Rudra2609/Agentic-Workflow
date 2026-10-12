Write a class `LRUCache`:

- `LRUCache(capacity: int)` — raise `ValueError` if capacity < 1.
- `get(key) -> value`, returning `-1` if the key is missing. A successful get marks the key as most recently used.
- `put(key, value)` — insert or update; updating also marks the key as most recently used.
  When inserting a new key into a full cache, first evict the least recently used key.
