"""Allocates memory until it is stopped: the memory limit (no swap) must stop it."""
blocks = []
while True:
    blocks.append(bytearray(32 * 1024 * 1024))
    print(f"{len(blocks) * 32} MB", flush=True)
