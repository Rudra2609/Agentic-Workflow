import pytest
from solution import TokenBucket

class FakeClock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t

def test_burst_then_block():
    c = FakeClock(); b = TokenBucket(rate=1, capacity=3, clock=c)
    assert [b.allow() for _ in range(4)] == [True, True, True, False]

def test_refill():
    c = FakeClock(); b = TokenBucket(rate=2, capacity=2, clock=c)
    b.allow(); b.allow()
    assert not b.allow()
    c.t = 0.5
    assert b.allow() and not b.allow()

def test_capacity_cap():
    c = FakeClock(); b = TokenBucket(rate=10, capacity=2, clock=c)
    c.t = 100
    assert [b.allow() for _ in range(3)] == [True, True, False]

def test_invalid():
    with pytest.raises(ValueError):
        TokenBucket(0, 1)
    with pytest.raises(ValueError):
        TokenBucket(1, 0)
