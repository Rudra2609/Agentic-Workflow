import threading
class SafeCounter:
    def __init__(self):
        self._v = 0
        self._lock = threading.Lock()
    def increment(self):
        with self._lock:
            self._v += 1
    @property
    def value(self):
        with self._lock:
            return self._v
def count_with_threads(n_threads, increments):
    c = SafeCounter()
    def work():
        for _ in range(increments):
            c.increment()
    ts = [threading.Thread(target=work) for _ in range(n_threads)]
    for t in ts: t.start()
    for t in ts: t.join()
    return c.value
