import threading
from solution import SafeCounter, count_with_threads

def test_helper():
    assert count_with_threads(8, 5000) == 40000
    assert count_with_threads(0, 10) == 0

def test_counter_under_contention():
    c = SafeCounter()
    def work():
        for _ in range(20000):
            c.increment()
    ts = [threading.Thread(target=work) for _ in range(10)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert c.value == 200000

def test_has_lock():
    import inspect, solution
    src = inspect.getsource(solution)
    assert "Lock" in src or "Semaphore" in src or "Condition" in src
