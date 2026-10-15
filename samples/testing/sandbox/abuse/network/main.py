"""Tries to reach the internet (DNS and a direct IP). Inside the sandbox both must fail."""
import socket

results = []
for target in [("1.1.1.1", 53), ("example.com", 80)]:
    try:
        socket.create_connection(target, timeout=3).close()
        results.append(f"REACHED {target[0]}")
    except OSError as exc:
        results.append(f"blocked {target[0]}: {type(exc).__name__}")
print("\n".join(results))
print("NETWORK_BLOCKED" if not any(r.startswith("REACHED") for r in results) else "NETWORK_OPEN")
