#!/usr/bin/env python3
"""Security checks (Sprint 6, Member 6). Exit 0 only if every executed check passed.

1. secret scan of the project tree (``scripts/secret_scan.sh``: key patterns, .env excluded);
2. leak scan of what the platform WRITES: ``logs/``, ``samples/llm_cache/``, ``data/`` (the dev keyring excepted): key
   patterns, plus the exact team keys and agent secrets configured in ``.env`` (reported by fingerprint only);
3. dependency audit: ``pip-audit`` on the locked backend requirements, ``npm audit`` on the frontend's production
   dependencies (need the network for the advisory databases; skipped with ``--offline`` or when offline);
4. the security test suite (``backend/tests/verify/security``: policy, tokens, rotation, injection, limits, leaks);
5. listeners: nothing on this machine's hmap ports listens on a non-loopback address.

Findings are triaged in ``docs/members/6/security-report.md``; this script writes ``reports/security-<date>.md``.
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from hmaptools.secrets import PATTERNS  # noqa: E402

LEAK_DIRS = ["logs", "samples/llm_cache", "data"]
SKIP = {ROOT / "data" / "security" / "agent_keys.json"}
PORTS = (8000, 3000, 5433, 5672, 15672, 9464, 16686, 4318, 9090, 3001)


def fp(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:8]


def env_secrets() -> list[str]:
    out: list[str] = []
    env = ROOT / ".env"
    if not env.is_file():
        return out
    for line in env.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("HMAP_GROQ_API_KEYS", "HMAP_GEMINI_API_KEYS", "HMAP_AGENT_SECRETS", "HMAP_CLOUD_API_KEY"):
            for part in value.split(","):
                part = part.strip().strip('"').split(":", 1)[-1] if key.strip() == "HMAP_AGENT_SECRETS" else \
                    part.strip().strip('"')
                if len(part) >= 12:
                    out.append(part)
    return out


def leak_scan() -> tuple[bool, str]:
    secrets = env_secrets()
    hits: list[str] = []
    files = 0
    for d in LEAK_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p in SKIP or p.stat().st_size > 20_000_000:
                continue
            files += 1
            try:
                text = p.read_text(errors="ignore")
            except OSError:
                continue
            for kind, pat in PATTERNS.items():
                if pat.search(text):
                    hits.append(f"{p.relative_to(ROOT)}: {kind}")
            for s in secrets:
                if s in text:
                    hits.append(f"{p.relative_to(ROOT)}: configured secret {fp(s)}")
    msg = f"{files} files scanned, {len(secrets)} configured secrets looked for"
    return not hits, msg + ("".join(f"\n    LEAK {h}" for h in hits[:20]) if hits else "")


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def pip_audit() -> tuple[str, str]:
    code, req = run(["uv", "export", "--frozen", "--no-hashes", "--no-dev", "--no-emit-project"], ROOT / "backend")
    if code != 0:
        return "FAIL", req[-400:]
    tmp = ROOT / "reports" / ".requirements-audit.txt"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(req)
    _, out = run(["uvx", "--quiet", "pip-audit", "-r", str(tmp), "--progress-spinner", "off", "--format", "json",
                     "--disable-pip", "--no-deps"], ROOT)
    tmp.unlink(missing_ok=True)
    try:
        data = json.loads(out[out.index("{"):]) if "{" in out else {}
    except ValueError:
        data = {}
    if not data and "No known vulnerabilities found" in out:
        return "PASS", "no known vulnerabilities in the locked backend dependencies"
    if not data:
        return "SKIP", "pip-audit unavailable or offline: " + out.splitlines()[-1][:200] if out else "no output"
    vulns = [(d["name"], d["version"], v["id"], ",".join(v.get("fix_versions") or []) or "no fix")
             for d in data.get("dependencies", []) for v in d.get("vulns", [])]
    text = f"{len(data.get('dependencies', []))} packages, {len(vulns)} known vulnerabilities"
    text += "".join(f"\n    {n} {v}: {i} (fix: {f})" for n, v, i, f in vulns)
    return ("PASS" if not vulns else "WARN"), text


def npm_audit() -> tuple[str, str]:
    if not shutil.which("npm"):
        return "SKIP", "npm not installed"
    _, out = run(["npm", "audit", "--omit=dev", "--json"], ROOT / "frontend")
    try:
        meta = json.loads(out).get("metadata", {}).get("vulnerabilities", {})
    except ValueError:
        return "SKIP", "npm audit unavailable or offline"
    high = meta.get("high", 0) + meta.get("critical", 0)
    text = ", ".join(f"{k} {v}" for k, v in meta.items() if k != "total") or "no data"
    return ("PASS" if high == 0 else "WARN"), f"production dependencies: {text}"


def listeners() -> tuple[bool, str]:
    if not shutil.which("lsof"):
        return True, "lsof not available: skipped"
    bad: list[str] = []
    for port in PORTS:
        _, out = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], ROOT)
        for line in out.splitlines()[1:]:
            addr = line.split()[8] if len(line.split()) > 8 else ""
            if addr and not re.match(r"^(127\.0\.0\.1|\[::1\]|localhost):", addr):
                bad.append(f"{port}: {addr} ({line.split()[0]})")
    return not bad, ("only loopback listeners on the hmap ports" if not bad else "; ".join(bad))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    results: list[tuple[str, str, str]] = []

    code, out = run([str(ROOT / "scripts" / "secret_scan.sh")], ROOT)
    results.append(("secret scan (tree)", "PASS" if code == 0 else "FAIL", out.splitlines()[-1] if out else ""))
    ok, msg = leak_scan()
    results.append(("leak scan (logs, recordings, data)", "PASS" if ok else "FAIL", msg))
    if args.offline:
        results += [("pip-audit (backend)", "SKIP", "--offline"), ("npm audit (frontend)", "SKIP", "--offline")]
    else:
        status, msg = pip_audit()
        results.append(("pip-audit (backend)", status, msg))
        status, msg = npm_audit()
        results.append(("npm audit (frontend)", status, msg))
    code, out = run(["uv", "run", "pytest", "-q", "-p", "no:randomly", "tests/verify/security"], ROOT / "backend")
    last = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "")
    results.append(("security tests", "PASS" if code == 0 else "FAIL", last))
    ok, msg = listeners()
    results.append(("loopback-only listeners", "PASS" if ok else "FAIL", msg))

    lines = [f"# Security check — {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
             "| Check | Result | Details |", "|---|---|---|"]
    for name, status, msg in results:
        print(f"{status:5s} {name}: {msg}")
        lines.append(f"| {name} | {status} | {msg.splitlines()[0] if msg else ''} |")
    details = [f"\n## {n}\n```\n{m}\n```" for n, s, m in results if "\n" in m]
    report = ROOT / "reports" / f"security-{dt.date.today().isoformat()}.md"
    report.parent.mkdir(exist_ok=True)
    report.write_text("\n".join(lines + details) + "\n")
    failed = [n for n, s, _ in results if s == "FAIL"]
    print(f"report: {report.relative_to(ROOT)}")
    print("SECURITY CHECK: " + ("PASS" if not failed else f"FAIL ({', '.join(failed)})"))
    print("(WARN = known vulnerable dependency: triage it in docs/members/6/security-report.md)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
