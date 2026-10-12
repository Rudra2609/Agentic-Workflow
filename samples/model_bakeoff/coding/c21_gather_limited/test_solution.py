import asyncio, pytest
from solution import gather_limited

def test_order_and_limit():
    state = {"now": 0, "max": 0}
    def make(i):
        async def run():
            state["now"] += 1; state["max"] = max(state["max"], state["now"])
            await asyncio.sleep(0.02 * (6 - i % 6))
            state["now"] -= 1
            return i
        return run
    out = asyncio.run(gather_limited([make(i) for i in range(10)], 3))
    assert out == list(range(10))
    assert state["max"] == 3

def test_factories_called_lazily():
    started = []
    def make(i):
        started.append(i)
        async def run():
            await asyncio.sleep(0.01); return i
        return run()
    out = asyncio.run(gather_limited([lambda i=i: make(i) for i in range(4)], 1))
    assert out == [0, 1, 2, 3]

def test_errors():
    async def bad():
        raise RuntimeError("x")
    with pytest.raises(RuntimeError):
        asyncio.run(gather_limited([lambda: bad()], 2))
    with pytest.raises(ValueError):
        asyncio.run(gather_limited([], 0))
