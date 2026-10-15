"""Floods stdout (about 200 MB): only the first --max-output bytes may be kept."""
import sys

line = "x" * 1023 + "\n"
for _ in range(200_000):
    sys.stdout.write(line)
