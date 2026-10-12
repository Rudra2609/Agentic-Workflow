import threading, time, pytest
from solution import parallel_map

def test_order_preserved():
    def slow(x):
        time.sleep(0.05 * (5 - x)); return x * x
    assert parallel_map(slow, [1, 2, 3, 4], 4) == [1, 4, 9, 16]

def test_concurrency_limit_respected_and_used():
    lock = threading.Lock(); state = {"now": 0, "max": 0}
    def f(x):
        with lock:
            state["now"] += 1; state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return x
    assert parallel_map(f, list(range(12)), 3) == list(range(12))
    assert state["max"] == 3

def test_exception_propagates():
    def f(x):
        if x == 2:
            raise KeyError("boom")
        return x
    with pytest.raises(KeyError):
        parallel_map(f, [1, 2, 3], 2)

def test_invalid_workers_and_empty():
    with pytest.raises(ValueError):
        parallel_map(lambda x: x, [1], 0)
    assert parallel_map(lambda x: x, [], 2) == []
