"""The code must not run as root, and must not be able to gain privileges."""
import os

print(f"uid={os.getuid()} gid={os.getgid()}")
print("NOT_ROOT" if os.getuid() != 0 else "RUNNING_AS_ROOT")
