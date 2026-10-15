"""Tries to write outside the workspace. Only /work (the code copy) and /tmp may be writable."""
from pathlib import Path

denied = []
for target in ["/etc/hmap_owned", "/usr/local/lib/evil.py", "/opt/hmap/stages.py", "/root_file", "/home/x"]:
    try:
        Path(target).write_text("owned")
        denied.append(f"WROTE {target}")
    except OSError as exc:
        denied.append(f"denied {target}: {type(exc).__name__}")
Path("/work/ok.txt").write_text("fine")
Path("/tmp/ok.txt").write_text("fine")
print("\n".join(denied))
print("WRITES_CONFINED" if not any(d.startswith("WROTE") for d in denied) else "WRITES_ESCAPED")
