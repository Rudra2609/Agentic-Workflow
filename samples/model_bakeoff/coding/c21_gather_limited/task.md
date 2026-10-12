Write `async def gather_limited(factories, limit: int) -> list` using `asyncio`.

`factories` is a list of zero-argument functions; calling one returns a new awaitable (coroutine).
Run them so that at most `limit` are in progress at the same time, and return their results in the same order as `factories`.
If any of them raises, the exception must propagate out of `gather_limited`. Raise `ValueError` if `limit < 1`.
