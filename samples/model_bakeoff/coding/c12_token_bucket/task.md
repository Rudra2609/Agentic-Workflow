Write a class `TokenBucket` for rate limiting.

- `TokenBucket(rate: float, capacity: int, clock=time.monotonic)` — `rate` tokens are added per second,
  up to `capacity`. The bucket starts full. `clock` is a zero-argument function returning seconds (tests inject a fake clock).
- `allow() -> bool`: refill based on time elapsed since the last refill, then if at least one token is available,
  consume one and return True; otherwise return False.
- Raise `ValueError` if rate <= 0 or capacity < 1.
