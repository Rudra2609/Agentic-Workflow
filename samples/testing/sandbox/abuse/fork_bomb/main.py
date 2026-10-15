"""A fork bomb: keep forking until it fails. The pids limit must stop it long before 500 processes."""
import os
import sys
import time

children = 0
try:
    for _ in range(500):
        pid = os.fork()
        if pid == 0:
            time.sleep(20)
            os._exit(0)
        children += 1
except OSError as exc:
    print(f"fork refused after {children} children: {type(exc).__name__}")
print(f"FORK_LIMITED {children}" if children < 500 else "FORK_UNLIMITED")
sys.stdout.flush()
os._exit(0)
