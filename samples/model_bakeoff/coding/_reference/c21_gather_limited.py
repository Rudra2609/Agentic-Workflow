import asyncio
async def gather_limited(factories, limit):
    if limit < 1:
        raise ValueError("limit")
    sem = asyncio.Semaphore(limit)
    async def one(f):
        async with sem:
            return await f()
    return list(await asyncio.gather(*(one(f) for f in factories)))
