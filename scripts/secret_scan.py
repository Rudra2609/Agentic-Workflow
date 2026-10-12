#!/usr/bin/env python3
"""Fail (exit 1) if a real-looking secret is anywhere in the project tree (excluding .env). Prints only a preview."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hmaptools.secrets import scan  # noqa: E402

findings = scan(ROOT)
for f in findings:
    print(f"SECRET? {f.kind:15s} {f.path}:{f.line}  {f.preview}")
print(f"{len(findings)} possible secret(s)" if findings else "no secrets found")
raise SystemExit(1 if findings else 0)
