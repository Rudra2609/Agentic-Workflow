"""Secret scan: fail if anything that looks like a real API key / private key is in the project tree.
`.env` is excluded by the tree rules (that is the ONE place keys belong). Placeholders like `gsk_...` don't match."""

import re
from dataclasses import dataclass
from pathlib import Path

from hmaptools.tree import manifest

PATTERNS: dict[str, re.Pattern[str]] = {
    "groq_key": re.compile(r"gsk_[A-Za-z0-9]{40,}"),
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "openai_key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{32,}"),
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{32,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
}
MAX_BYTES = 2_000_000


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    preview: str


def scan(root: Path) -> list[Finding]:
    out: list[Finding] = []
    for rel in manifest(root):
        p = root / rel
        if p.stat().st_size > MAX_BYTES:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for kind, pat in PATTERNS.items():
                m = pat.search(line)
                if m:
                    s = m.group(0)
                    out.append(Finding(rel, n, kind, s[:6] + "…" + s[-2:]))  # never print the whole secret
    return out
