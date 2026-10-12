import time
class TokenBucket:
    def __init__(self, rate, capacity, clock=time.monotonic):
        if rate <= 0 or capacity < 1:
            raise ValueError("bad params")
        self.rate, self.capacity, self.clock = rate, capacity, clock
        self.tokens = float(capacity)
        self.last = clock()
    def allow(self):
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
