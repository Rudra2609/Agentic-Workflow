#!/usr/bin/env python3
"""Build the seeded-hallucination benchmark (Sprint 6 item 6.9, prepared ahead by Member 6).

Input: real research reports produced by Sprint 5's research agent (``source_reports/``, offline replay of the 10
gold questions + the TCP-chat demo brief) and the saved pages they cite (``pages/``, all freely licensed). Output:
``benchmark.jsonl``. Every planted error below is written by hand; the script only applies them and refuses to build
if a "fake" quote happens to exist in its page or a "real" quote does not. Plain Python 3.11, no project imports.

    python3 samples/verify/build_benchmark.py          # rebuild benchmark.jsonl (+ synthetic counter pages)
    python3 samples/verify/check_benchmark.py          # validate it
"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "source_reports"
PAGES = HERE / "pages"

# ---------------------------------------------------------------------------------------------- helpers


def norm(text: str) -> str:
    """Typography-insensitive form (whitespace, curly quotes, dashes) - the same idea as Sprint 5's quote check."""
    table = str.maketrans({chr(c): "'" for c in (0x2018, 0x2019)} | {chr(c): '"' for c in (0x201C, 0x201D)}
                          | {chr(c): "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014)} | {chr(0x00A0): " "})
    return " ".join(text.translate(table).split())


def swap(text: str, find: str, repl: str) -> str:
    """Replace ``find`` in ``text``; when the typography differs (hyphen kinds, curly quotes), on the normalised
    text."""
    if find in text:
        return text.replace(find, repl)
    assert norm(find) in norm(text), (find, text[:80])
    return norm(text).replace(norm(find), repl)


def load_reports() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(REPORTS.glob("*.json"))}


def page_file(sha: str) -> str:
    return f"pages/{sha[:16]}.json"


def page_text(sha: str) -> str:
    return json.loads((HERE / page_file(sha)).read_text(encoding="utf-8"))["text"]


REP = load_reports()


def claim(report: str, cid: str) -> dict:
    return next(c for c in REP[report]["claims"] if c["id"] == cid)


def evidence(report: str, eid: str) -> dict:
    e = next(e for e in REP[report]["evidence"] if e["id"] == eid)
    return {"id": e["id"], "url": e["url"], "quote": e["quote"], "content_sha256": e["content_sha256"],
            "page": page_file(e["content_sha256"])}


def claim_evidence(report: str, cid: str) -> list[dict]:
    return [evidence(report, i) for i in claim(report, cid)["evidence_ids"]]


# ---------------------------------------------------------------------------------------------- the items

# 20 clean controls: real claims that their quotes support (measures false alarms)
CLEAN = [("demo_tcp_chat", "C3"), ("demo_tcp_chat", "C6"), ("demo_tcp_chat", "C8"), ("q01_tcp_concurrency", "C1"),
         ("q01_tcp_concurrency", "C2"), ("q01_tcp_concurrency", "C3"), ("q03_latency", "C3"),
         ("q05_django_fastapi", "C1"), ("q05_django_fastapi", "C2"), ("q06_token_scheme", "C1"),
         ("q06_token_scheme", "C2"), ("q06_token_scheme", "C3"), ("q06_token_scheme", "C4"),
         ("q07_react_state", "C1"), ("q07_react_state", "C3"), ("q08_localstorage", "C3"), ("q09_argparse", "C1"),
         ("q09_argparse", "C4"), ("q10_strategy", "C1"), ("q10_strategy", "C2")]

# 15 fake quotes: (report, claim, evidence id, text in the quote, replacement) - the quote is no longer in its page.
# A replacement of None means the whole quote is invented.
FAKE_QUOTES = [
    ("q06_token_scheme", "C4", "E6", "SHA-256 (HS256) and RSA signature with SHA-256 (RS256)",
     "SHA-512 (HS512) and RSA signature with SHA-512 (RS512)"),
    ("q01_tcp_concurrency", "C3", "E3", "only one thread can execute", "only two threads can execute"),
    ("demo_tcp_chat", "C4", "E5", ">= 20%", ">= 40%"),
    ("q09_argparse", "C1", "E1", "the recommended command-line parsing module", "the only command-line parsing module"),
    ("q10_strategy", "C1", "E1", "behavioral software design pattern", "creational software design pattern"),
    ("q07_react_state", "C3", "E3", "does not require a centralized store", "does not require a reducer function"),
    ("q06_token_scheme", "C1", "E1", "never saved in server memory", "never saved in client memory"),
    ("demo_tcp_chat", "C2", "E14", "since Version 3.4", "since Version 3.2"),
    ("q03_latency", "C3", "E2", "both seconds and nanoseconds", "both seconds and microseconds"),
    ("q05_django_fastapi", "C2", "E2", "and a powerful ORM", "a powerful ORM and a built-in task queue"),
    ("q08_localstorage", "C3", "E10", "does not include any of their associated methods",
     "includes all of their associated methods"),
    ("demo_tcp_chat", "C6", "E12", "outbound network buffer space", "inbound network buffer space"),
    ("q06_token_scheme", "C2", "E2", "in the Authorization HTTP header", "in a browser cookie"),
    ("q09_argparse", "C4", "E4", "the default recommended standard library module", "the only supported module"),
    ("q10_strategy", "C2", "E2", None, "Strategy objects must always be implemented as stateless singletons"),
]

# 15 wrong numbers / details in the claim: (report, claim, text in the claim, replacement, note). Quotes stay real.
WRONG_NUMBERS = [
    ("demo_tcp_chat", "C4", "20% or more", "5% or more", "the paper reports a drop of >= 20%"),
    ("demo_tcp_chat", "C2", "since Python 3.4", "since Python 3.7", "the source says Version 3.4"),
    ("q06_token_scheme", "C4", "HMAC‑SHA256 (HS256) and RSA‑SHA256 (RS256)", "HMAC‑SHA1 (HS1) and RSA‑SHA512 (RS512)",
     "the source names SHA-256 for both"),
    ("q03_latency", "C2", "millisecond‑resolution", "microsecond‑resolution", "the source says milliseconds"),
    ("q03_latency", "C3", "second and nanosecond precision", "second and millisecond precision",
     "the source says nanoseconds"),
    ("q01_tcp_concurrency", "C3", "only one thread", "at most four threads", "the source says one thread"),
    ("demo_tcp_chat", "C3", "only one thread", "only two threads", "the source says one thread"),
    ("demo_tcp_chat", "C4", "beyond a few hundred threads", "beyond 32 threads", "the source says N >= 512"),
    ("q09_argparse", "C2", "lower‑level optparse", "higher‑level optparse", "the source says lower level"),
    ("q09_argparse", "C3", "the C getopt() functions", "Java's getopt() functions", "the source says C"),
    ("q07_react_state", "C1", "useState is a Hook", "useEffect is a Hook", "the source names useState"),
    ("q10_strategy", "C1", "behavioral design pattern", "structural design pattern", "the source says behavioral"),
    ("q06_token_scheme", "C1", "the server does not store", "the client does not store",
     "the source says server memory"),
    ("q08_localstorage", "C3", "are not included", "are included", "the source says methods are not included"),
    ("q06_token_scheme", "C3", "can be lost if", "is kept even if", "the source says statelessness is lost"),
]

# 15 unsupported claims: (report, claim whose evidence is kept, new claim text)
UNSUPPORTED = [
    ("q06_token_scheme", "C2", "The JWT standard requires tokens to be refreshed every 15 minutes."),
    ("q01_tcp_concurrency", "C1", "asyncio is always faster than threading for every TCP server."),
    ("q07_react_state", "C2", "useReducer was introduced in React 15 to replace Redux entirely."),
    ("q09_argparse", "C5", "argparse can also read configuration files in YAML format automatically."),
    ("q10_strategy", "C2", "The strategy pattern was first described by Martin Fowler in 2002."),
    ("demo_tcp_chat", "C7", "select works only on Linux and cannot be used on Windows."),
    ("q05_django_fastapi", "C3", "FastAPI is the fastest Python web framework in every benchmark."),
    ("q08_localstorage", "C4", "localStorage can hold up to 100 MB per site in every browser."),
    ("q03_latency", "C1", "Python's time.time() has nanosecond accuracy on every operating system."),
    ("q06_token_scheme", "C5", "The alg=none vulnerability is still present in all current JWT libraries."),
    ("demo_tcp_chat", "C5", "The GIL was removed completely from CPython in Python 3.12."),
    ("q02_broadcast", "C1", "Message-oriented middleware guarantees exactly-once delivery of every message."),
    ("q05_django_fastapi", "C2", "Django's ORM supports only PostgreSQL databases."),
    ("q09_argparse", "C1", "argparse was added to the Python standard library in Python 2.0."),
    ("demo_tcp_chat", "C1", "Python threads run Python code on separate CPU cores in parallel."),
]

# 15 contradictions: (report, real supported claim, synthetic counter source: host, title, sentence)
CONTRADICTIONS = [
    ("q06_token_scheme", "C1", "auth-notes.example.test", "JWT in production",
     "Most production JWT deployments keep a server-side session record for every issued token, so in practice "
     "JWT authentication is stateful."),
    ("q09_argparse", "C1", "pycli-blog.example.test", "Choosing a CLI library",
     "The Python documentation now recommends the third-party click package instead of argparse for all new "
     "command-line programs."),
    ("q01_tcp_concurrency", "C3", "fastpython.example.test", "Threads in CPython 3.13",
     "Since Python 3.13 the global interpreter lock no longer limits CPU-bound threads in the standard CPython "
     "build."),
    ("q06_token_scheme", "C4", "crypto-weekly.example.test", "JWT algorithms in 2026",
     "The most common JWT algorithms in use are ES256 and EdDSA; HS256 and RS256 are rarely used today."),
    ("demo_tcp_chat", "C2", "py-history.example.test", "When asyncio arrived",
     "asyncio became part of the Python standard library only in Python 3.6."),
    ("q10_strategy", "C1", "patterns-wiki.example.test", "Pattern catalogue",
     "The strategy pattern is classified as a structural design pattern in the original Gang of Four catalogue."),
    ("q07_react_state", "C3", "react-tips.example.test", "Global state with hooks",
     "useReducer stores its state in a single global store that is shared by every component of the "
     "application."),
    ("q08_localstorage", "C3", "js-faq.example.test", "Serialising objects",
     "Modern JSON serialisation in JavaScript keeps an object's methods, so JSON.parse restores them."),
    ("q03_latency", "C3", "jvm-time.example.test", "Java time precision",
     "Java's Instant class stores time with millisecond precision only."),
    ("demo_tcp_chat", "C4", "edge-ai.example.test", "Thread pools on edge devices",
     "Increasing a Python thread pool beyond 512 threads never reduces performance; throughput keeps rising "
     "linearly with the number of threads."),
    ("q05_django_fastapi", "C2", "web-frameworks.example.test", "Django add-ons",
     "Django does not ship an admin interface; it must be installed as a separate third-party package."),
    ("q06_token_scheme", "C2", "api-security.example.test", "Sending tokens",
     "JWTs must be sent only in cookies; sending them in the Authorization header is not allowed by the "
     "standard."),
    ("demo_tcp_chat", "C8", "netprog.example.test", "Socket buffers",
     "Data written to a socket is always transmitted immediately; output buffers never delay a reply."),
    ("q09_argparse", "C2", "stdlib-news.example.test", "Removed modules",
     "optparse was removed from the Python standard library in Python 3.0."),
    ("q01_tcp_concurrency", "C2", "concurrency101.example.test", "Threads and memory",
     "Each Python thread gets its own private copy of memory, so threads never share variables."),
]

# 6 natural errors: real claims the Sprint 5 agent wrote that go beyond their quotes (found by hand)
NATURAL = [
    ("q06_token_scheme", "C6", "the quote is about FastAPI's overall overhead; it says nothing about token handling",
     "hard"),
    ("q05_django_fastapi", "C5", "the quote is about Uvicorn vs Starlette; the claim misreads it as FastAPI needing "
     "more code than Starlette", "medium"),
    ("q02_broadcast", "C2", "the quote describes broadcast in SPMD parallel programs; 'non-blocking dissemination' is "
     "not in it", "hard"),
    ("q08_localstorage", "C1", "the quote says JSON is built into ECMAScript; it never mentions localStorage",
     "medium"),
    ("q08_localstorage", "C2", "the quote lists textual formats; storing them in localStorage is not in it",
     "medium"),
    ("demo_tcp_chat", "C7", "the quote says select tells whether you will block; 'back-pressure handling for slow "
     "receivers' is the agent's extrapolation", "hard"),
]


def synthetic_page(host: str, title: str, sentence: str) -> dict:
    text = (f"{title}\n\n{sentence}\n\nThis page was written for the Member 6 verification benchmark. It is a "
            "deliberately contradicting source: the statement above is planted, not taken from any real "
            "publication, and is used to test cross-source conflict detection.")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"url": f"https://{host}/{title.lower().replace(' ', '-')}", "title": title, "kind": "web",
            "license": "written for this benchmark (synthetic)", "content_sha256": sha,
            "retrieved_at": "2026-10-14T00:00:00+00:00", "text": text, "synthetic": True}


def build() -> list[dict]:
    items: list[dict] = []

    def add(**kw: object) -> None:
        items.append({"id": f"V{len(items) + 1:03d}", **kw})

    for report, cid in CLEAN:
        add(kind="clean", source={"report": report, "claim_id": cid}, claim=claim(report, cid)["text"],
            evidence=claim_evidence(report, cid), counter_evidence=[], difficulty="easy",
            expected={"verdict": "VERIFIED", "l1_quotes_verbatim": True, "error_in": "none"},
            explanation="real claim from Sprint 5; its quotes support it")

    for report, cid, eid, find, repl in FAKE_QUOTES:
        ev = claim_evidence(report, cid)
        target = next(e for e in ev if e["id"] == eid)
        original = target["quote"]
        if find is None:
            target["quote"] = repl
        else:
            target["quote"] = swap(original, find, repl)
        assert norm(target["quote"]) not in norm(page_text(target["content_sha256"])), (report, cid)
        add(kind="fake_quote", source={"report": report, "claim_id": cid}, claim=claim(report, cid)["text"],
            evidence=ev, counter_evidence=[], difficulty="easy",
            expected={"verdict": "UNSUPPORTED", "l1_quotes_verbatim": False, "error_in": f"evidence {eid} quote"},
            changed={"field": f"evidence {eid} quote", "from": find or original, "to": repl},
            explanation="the quote is not in the saved page (its hash still points to the real page)")

    for report, cid, find, repl, note in WRONG_NUMBERS:
        text = claim(report, cid)["text"]
        add(kind="wrong_number", source={"report": report, "claim_id": cid}, claim=swap(text, find, repl),
            evidence=claim_evidence(report, cid), counter_evidence=[], difficulty="medium",
            expected={"verdict": "UNSUPPORTED", "l1_quotes_verbatim": True, "error_in": "claim"},
            changed={"field": "claim", "from": find, "to": repl}, explanation=note)

    for report, cid, text in UNSUPPORTED:
        add(kind="unsupported_claim", source={"report": report, "claim_id": cid}, claim=text,
            evidence=claim_evidence(report, cid), counter_evidence=[], difficulty="medium",
            expected={"verdict": "UNSUPPORTED", "l1_quotes_verbatim": True, "error_in": "claim"},
            changed={"field": "claim", "from": claim(report, cid)["text"], "to": text},
            explanation="the cited quotes are real but do not say this")

    for n, (report, cid, host, title, sentence) in enumerate(CONTRADICTIONS, start=1):
        page = synthetic_page(host, title, sentence)
        (PAGES / f"synthetic-{n:02d}.json").write_text(json.dumps(page, indent=1, ensure_ascii=False) + "\n",
                                                        encoding="utf-8")
        counter = {"id": "X1", "url": page["url"], "quote": sentence, "content_sha256": page["content_sha256"],
                   "page": f"pages/synthetic-{n:02d}.json"}
        add(kind="contradiction", source={"report": report, "claim_id": cid}, claim=claim(report, cid)["text"],
            evidence=claim_evidence(report, cid), counter_evidence=[counter], difficulty="medium",
            expected={"verdict": "CONFLICTING", "l1_quotes_verbatim": True, "error_in": "sources disagree"},
            explanation="the claim is supported by its real source, and a second (synthetic) source says the opposite")

    for report, cid, note, difficulty in NATURAL:
        add(kind="natural", source={"report": report, "claim_id": cid}, claim=claim(report, cid)["text"],
            evidence=claim_evidence(report, cid), counter_evidence=[], difficulty=difficulty,
            expected={"verdict": "UNSUPPORTED", "l1_quotes_verbatim": True, "error_in": "claim"},
            explanation=f"real Sprint 5 output, not planted: {note}")
    return items


def main() -> None:
    items = build()
    out = HERE / "benchmark.jsonl"
    out.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    kinds: dict[str, int] = {}
    for i in items:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    print(f"wrote {out.name}: {len(items)} items {kinds}")


if __name__ == "__main__":
    main()
