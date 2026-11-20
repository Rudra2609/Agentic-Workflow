#!/usr/bin/env python3
"""Builds the six benchmark tasks added in Sprint 7 (plan D25). Plain Python 3.11; re-run to rebuild them.

    python3 samples/coding/build_sprint7_tasks.py

- ``x1_tcp_nick``, ``x2_cli_top_words``, ``x3_pkg_inventory``: **greenfield from a template**. ``task.json`` names
  the template; the agent starts from an EMPTY workspace (it must pick the template itself), the fairness check
  starts from the template. The hidden tests need more than the template (a /nick command, a subcommand, a module).
  x1 is the Sprint 7 Definition-of-Done task "TCP chat scaffold end-to-end".
- ``d1_discount_percent``, ``d2_session_minutes``, ``d3_csv_quotes``: **decoy repositories** (16–19 files) for the
  locator: deprecated copies, look-alike modules and words from the bug report spread over many files. The prototype
  locator's 7/7 was on 3–5-file repos; these measure top-1 / top-3 on something harder (``"decoy": true``).
"""

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"


def edits(*blocks: tuple[str, str, str]) -> str:
    def nl(text: str) -> str:
        return text if not text or text.endswith("\n") else text + "\n"
    return "".join(f"{p}\n<<<<<<< SEARCH\n{nl(s)}=======\n{nl(r)}>>>>>>> REPLACE\n" for p, s, r in blocks)


def write(task_id: str, meta: dict, starter: dict[str, str] | None, hidden: dict[str, str], gold: str) -> None:
    root = TASKS / task_id
    if root.exists():
        shutil.rmtree(root)
    (root / "hidden_tests").mkdir(parents=True)
    (root / "task.json").write_text(json.dumps({"id": task_id, **meta}, indent=1) + "\n", encoding="utf-8")
    (root / "gold.edits").write_text(gold, encoding="utf-8")
    for name, text in hidden.items():
        (root / "hidden_tests" / name).write_text(text, encoding="utf-8")
    if starter is not None:
        for rel, text in starter.items():
            (root / "starter" / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / "starter" / rel).write_text(text, encoding="utf-8")


# ============================================================================== greenfield from a template

write("x1_tcp_nick", {
    "kind": "greenfield", "template": "tcp_server_client",
    "objective": "Build a multi-client TCP chat server and client. Every message a client sends is broadcast to all "
                 "other connected clients, prefixed with the sender's name. A client can choose its name by sending "
                 "'/nick NAME'; until then its name is clientN. The /nick line itself is not broadcast.",
    "acceptance_criteria": ["two clients connected at the same time both get each other's messages",
                            "after '/nick alice' the other clients receive 'alice: hello' for 'hello'",
                            "a client that disconnects does not break the others"],
    "files_to_edit": ["server.py"]}, None, {"test_x1_tcp_nick.py": '''import time
import unittest

from client import ChatClient
from server import ChatServer


class NickTest(unittest.TestCase):
    def setUp(self):
        self.server = ChatServer("127.0.0.1", 0)
        self.port = self.server.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.server.stop()

    def connect(self):
        c = ChatClient("127.0.0.1", self.port, timeout=3)
        self.clients.append(c)
        deadline = time.time() + 3
        while self.server.client_count() < len(self.clients) and time.time() < deadline:
            time.sleep(0.01)
        return c

    def test_nick_prefixes_messages_and_is_not_broadcast(self):
        a, b = self.connect(), self.connect()
        a.send("/nick alice")
        time.sleep(0.2)
        a.send("hello")
        self.assertEqual(b.receive(), "alice: hello")

    def test_default_names_and_concurrent_clients(self):
        a, b, c = self.connect(), self.connect(), self.connect()
        b.send("hi")
        self.assertTrue(a.receive().endswith(": hi"))
        self.assertTrue(c.receive().endswith(": hi"))


if __name__ == "__main__":
    unittest.main()
'''}, edits(("server.py", """                for line in reader.feed(data):
                    if line.strip():
""", """                for line in reader.feed(data):
                    if line.startswith("/nick "):
                        name = line[len("/nick "):].strip()
                        if name:
                            with self._lock:
                                self._clients[conn] = name
                        continue
                    if line.strip():
""")))

write("x2_cli_top_words", {
    "kind": "greenfield", "template": "cli",
    "objective": "Command-line tool: add a subcommand 'top PATH [-n N]' that prints the N most frequent words of a "
                 "text file (default 3), one 'word count' per line, most frequent first, ties in alphabetical order. "
                 "Words are lower-cased runs of letters.",
    "acceptance_criteria": ["'top notes.txt -n 2' prints the two most frequent words with their counts",
                            "ties are ordered alphabetically", "a missing file exits with code 1"],
    "files_to_edit": ["cli.py"]}, None, {"test_x2_cli_top_words.py": '''import contextlib
import io
import os
import tempfile
import unittest

from cli import main


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(args))
    return code, out.getvalue().strip().splitlines()


class TopTest(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir=".") as f:
            f.write("The cat and the dog. The END, and the cat!\\n")
        self.path = f.name

    def tearDown(self):
        os.unlink(self.path)

    def test_top_two(self):
        self.assertEqual(run("top", self.path, "-n", "2"), (0, ["the 4", "and 2"]))

    def test_default_three_with_tie_order(self):
        self.assertEqual(run("top", self.path), (0, ["the 4", "and 2", "cat 2"]))

    def test_missing_file(self):
        self.assertEqual(run("top", "no-such-file.txt")[0], 1)


if __name__ == "__main__":
    unittest.main()
'''}, edits(("cli.py", """import argparse
import sys
""", """import argparse
import re
import sys
from collections import Counter
"""), ("cli.py", """def read_input(path: str) -> str:""", """def top_words(text: str, n: int) -> list[tuple[str, int]]:
    counts = Counter(re.findall(r"[a-z]+", text.lower()))
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def read_input(path: str) -> str:"""), ("cli.py", """    p.add_argument("path", help="a file, or - for stdin")
    return parser""", """    p.add_argument("path", help="a file, or - for stdin")
    t = sub.add_parser("top", help="the most frequent words")
    t.add_argument("path", help="a file, or - for stdin")
    t.add_argument("-n", type=int, default=3)
    return parser"""), ("cli.py", """            print(" ".join(f"{k}={v}" for k, v in result.items()))
            return 0
""", """            print(" ".join(f"{k}={v}" for k, v in result.items()))
            return 0
        if args.command == "top":
            for word, n in top_words(read_input(args.path), args.n):
                print(f"{word} {n}")
            return 0
""")))

write("x3_pkg_inventory", {
    "kind": "greenfield", "template": "python_package",
    "objective": "Python package: add a module app/inventory.py with class Inventory: add(item, qty) adds stock, "
                 "remove(item, qty) takes stock away and raises ValueError when there is not enough, stock(item) "
                 "returns the quantity (0 for unknown items). Quantities must be positive integers (ValueError "
                 "otherwise).",
    "acceptance_criteria": ["add then stock returns the sum", "removing more than in stock raises ValueError and "
                            "changes nothing", "qty 0 or negative raises ValueError"],
    "files_to_edit": ["app/inventory.py"]}, None, {"test_x3_pkg_inventory.py": '''import unittest

from app.inventory import Inventory


class InventoryTest(unittest.TestCase):
    def test_add_and_stock(self):
        inv = Inventory()
        inv.add("pen", 3)
        inv.add("pen", 2)
        self.assertEqual(inv.stock("pen"), 5)
        self.assertEqual(inv.stock("ink"), 0)

    def test_remove_too_much_changes_nothing(self):
        inv = Inventory()
        inv.add("pen", 2)
        with self.assertRaises(ValueError):
            inv.remove("pen", 3)
        self.assertEqual(inv.stock("pen"), 2)
        inv.remove("pen", 2)
        self.assertEqual(inv.stock("pen"), 0)

    def test_bad_quantities(self):
        inv = Inventory()
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                inv.add("pen", bad)


if __name__ == "__main__":
    unittest.main()
'''}, edits(("app/inventory.py", "", '''"""Stock of items."""


class Inventory:
    def __init__(self) -> None:
        self._stock: dict[str, int] = {}

    @staticmethod
    def _check(qty: int) -> None:
        if not isinstance(qty, int) or qty <= 0:
            raise ValueError("quantity must be a positive integer")

    def add(self, item: str, qty: int) -> None:
        self._check(qty)
        self._stock[item] = self._stock.get(item, 0) + qty

    def remove(self, item: str, qty: int) -> None:
        self._check(qty)
        if self._stock.get(item, 0) < qty:
            raise ValueError(f"not enough {item}")
        self._stock[item] -= qty

    def stock(self, item: str) -> int:
        return self._stock.get(item, 0)
''')))

# ======================================================================================== decoy repositories


def filler(name: str, words: str) -> str:
    """A plausible, unrelated helper module (the bulk of a decoy repo)."""
    return f'''"""{name}: {words}."""


def describe() -> str:
    return "{words}"
'''


D1 = {
    "README.md": "# shop\n\nCheckout with discount codes, tax and currency conversion.\n",
    "pricing/__init__.py": "",
    "pricing/discounts.py": '''"""Discount codes applied at checkout."""

CODES = {"SAVE10": ("percent", 10), "SAVE25": ("percent", 25), "FLAT5": ("amount", 5)}


def apply_discount(total: float, code: str | None) -> float:
    """Total after the discount code (unknown or empty codes change nothing)."""
    kind, value = CODES.get((code or "").upper(), (None, 0))
    if kind == "percent":
        return round(total - value, 2)
    if kind == "amount":
        return round(max(0.0, total - value), 2)
    return total
''',
    "pricing/legacy_discounts.py": '''"""DEPRECATED: the old discount table (kept for the 2023 reports, not used at checkout)."""

OLD_CODES = {"SAVE10": 10, "WINTER": 15}


def legacy_discount_percent(code: str) -> int:
    """Percent of an old discount code (0 if unknown)."""
    return OLD_CODES.get(code, 0)
''',
    "pricing/tax.py": '''"""Sales tax per region."""

RATES = {"default": 0.08, "food": 0.0}


def add_tax(total: float, region: str = "default") -> float:
    return round(total * (1 + RATES.get(region, RATES["default"])), 2)
''',
    "pricing/currency.py": filler("currency", "convert totals between currencies with fixed rates"),
    "checkout.py": '''"""Checkout: discount first, then tax."""

from pricing.discounts import apply_discount
from pricing.tax import add_tax


def checkout(total: float, code: str | None = None, region: str = "default") -> float:
    return add_tax(apply_discount(total, code), region)
''',
    "reports/__init__.py": "",
    "reports/discount_report.py": '''"""Monthly report: how often each discount code was used and the percent saved per order total."""


def usage(orders: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for o in orders:
        code = o.get("discount_code")
        if code:
            out[code] = out.get(code, 0) + 1
    return out
''',
    "reports/sales_report.py": filler("sales report", "orders per day and total revenue"),
    "models.py": filler("models", "order, line item and customer records"),
    "storage.py": filler("storage", "save and load orders as json"),
    "api.py": filler("api", "http handlers for cart and checkout pages"),
    "config.py": filler("config", "settings read from environment variables"),
    "utils/__init__.py": "",
    "utils/numbers.py": '''"""Number helpers."""


def percent_of(value: float, percent: float) -> float:
    """``percent`` % of ``value``."""
    return value * percent / 100
''',
    "utils/strings.py": filler("strings", "slug and title helpers"),
    "utils/dates.py": filler("dates", "parse and format order dates"),
    "tests/__init__.py": "",
    "tests/test_tax.py": '''import unittest

from pricing.tax import add_tax


class TaxTest(unittest.TestCase):
    def test_default_rate(self):
        self.assertEqual(add_tax(100), 108.0)
''',
}
write("d1_discount_percent", {
    "kind": "bugfix", "decoy": True,
    "objective": "Bug report: discount code SAVE10 takes 10 off the order instead of 10 percent. An order of 200 "
                 "should cost 180 with SAVE10 (before tax), and SAVE25 should take a quarter off.",
    "acceptance_criteria": ["apply_discount(200, 'SAVE10') == 180", "apply_discount(80, 'SAVE25') == 60",
                            "FLAT5 still takes 5 off"],
    "files_to_edit": ["pricing/discounts.py"]}, D1, {"test_d1_discount_percent.py": '''import unittest

from pricing.discounts import apply_discount


class DiscountTest(unittest.TestCase):
    def test_percent_codes(self):
        self.assertEqual(apply_discount(200, "SAVE10"), 180)
        self.assertEqual(apply_discount(80, "save25"), 60)

    def test_amount_and_unknown(self):
        self.assertEqual(apply_discount(50, "FLAT5"), 45)
        self.assertEqual(apply_discount(50, "NOPE"), 50)


if __name__ == "__main__":
    unittest.main()
'''}, edits(("pricing/discounts.py", "        return round(total - value, 2)\n",
             "        return round(total * (1 - value / 100), 2)\n")))

D2 = {
    "README.md": "# portal\n\nLogin sessions, API tokens, a small cache and a job scheduler.\n",
    "auth/__init__.py": "",
    "auth/sessions.py": '''"""Login sessions: a session expires after its timeout (minutes) without activity."""

SESSION_TIMEOUT_MINUTES = 30


def is_expired(last_seen: float, now: float, timeout_minutes: int = SESSION_TIMEOUT_MINUTES) -> bool:
    """True when more than ``timeout_minutes`` passed since ``last_seen`` (times in seconds)."""
    return now - last_seen > timeout_minutes
''',
    "auth/tokens.py": '''"""API tokens: expire after a fixed number of seconds."""

TOKEN_TTL_SECONDS = 3600


def token_expired(issued_at: float, now: float, ttl_seconds: int = TOKEN_TTL_SECONDS) -> bool:
    return now - issued_at > ttl_seconds
''',
    "auth/old_sessions.py": '''"""DEPRECATED session store (cookie based); kept until the migration ends. Not used for timeouts."""


def session_cookie_name() -> str:
    return "sid"
''',
    "auth/passwords.py": filler("passwords", "hash and verify login passwords"),
    "cache/__init__.py": "",
    "cache/ttl_cache.py": '''"""A cache whose entries expire after a timeout in seconds."""

import time


class TTLCache:
    def __init__(self, timeout_seconds: float = 60) -> None:
        self.timeout = timeout_seconds
        self.items: dict[str, tuple[float, object]] = {}

    def get(self, key: str) -> object | None:
        hit = self.items.get(key)
        if hit is None or time.time() - hit[0] > self.timeout:
            return None
        return hit[1]

    def put(self, key: str, value: object) -> None:
        self.items[key] = (time.time(), value)
''',
    "scheduler/__init__.py": "",
    "scheduler/timeouts.py": '''"""Job timeouts: a job that runs longer than its timeout (minutes) is killed."""


def job_timed_out(started: float, now: float, timeout_minutes: int) -> bool:
    return now - started > timeout_minutes * 60
''',
    "scheduler/jobs.py": filler("jobs", "run nightly cleanup jobs"),
    "web/__init__.py": "",
    "web/login.py": '''"""Login page handlers: start a session, log out when it expired."""

from auth.sessions import is_expired


def still_logged_in(last_seen: float, now: float) -> bool:
    return not is_expired(last_seen, now)
''',
    "web/pages.py": filler("pages", "render the dashboard and profile pages"),
    "users.py": filler("users", "user records and roles"),
    "audit.py": filler("audit", "write login and logout events to the audit log"),
    "settings.py": filler("settings", "timeouts and limits read from the environment"),
    "tests/__init__.py": "",
    "tests/test_tokens.py": '''import unittest

from auth.tokens import token_expired


class TokenTest(unittest.TestCase):
    def test_ttl(self):
        self.assertFalse(token_expired(0, 3600))
        self.assertTrue(token_expired(0, 3601))
''',
}
write("d2_session_minutes", {
    "kind": "bugfix", "decoy": True,
    "objective": "Bug report: users are logged out after about 30 seconds of inactivity although the session "
                 "timeout is 30 minutes.",
    "acceptance_criteria": ["a session seen 60 seconds ago is still valid", "a session seen 31 minutes ago has "
                            "expired"],
    "files_to_edit": ["auth/sessions.py"]}, D2, {"test_d2_session_minutes.py": '''import unittest

from auth.sessions import is_expired
from web.login import still_logged_in


class SessionTest(unittest.TestCase):
    def test_minutes_not_seconds(self):
        self.assertFalse(is_expired(0, 60))
        self.assertFalse(is_expired(0, 30 * 60))
        self.assertTrue(is_expired(0, 31 * 60))
        self.assertTrue(still_logged_in(1000, 1000 + 25 * 60))


if __name__ == "__main__":
    unittest.main()
'''}, edits(("auth/sessions.py", "    return now - last_seen > timeout_minutes\n",
             "    return now - last_seen > timeout_minutes * 60\n")))

D3 = {
    "README.md": "# dataio\n\nReaders and writers for CSV, TSV, JSON and INI files.\n",
    "io_utils/__init__.py": "",
    "io_utils/csv_reader.py": '''"""Read CSV text into rows of fields."""


def split_line(line: str) -> list[str]:
    """Fields of one CSV line."""
    return [field.strip() for field in line.rstrip("\\n").split(",")]


def read_rows(text: str) -> list[list[str]]:
    return [split_line(line) for line in text.splitlines() if line.strip()]
''',
    "io_utils/csv_writer.py": '''"""Write rows as CSV: fields with a comma or a quote are quoted, quotes doubled."""


def quote_field(field: str) -> str:
    if "," in field or '"' in field:
        return '"' + field.replace('"', '""') + '"'
    return field


def write_line(fields: list[str]) -> str:
    return ",".join(quote_field(f) for f in fields)
''',
    "io_utils/tsv_reader.py": '''"""Read TSV lines (fields split on tabs)."""


def split_tsv_line(line: str) -> list[str]:
    return line.rstrip("\\n").split("\\t")
''',
    "legacy/__init__.py": "",
    "legacy/csv_split_old.py": '''"""DEPRECATED: the first CSV splitter (no quotes support). Use io_utils.csv_reader."""


def old_split(line: str) -> list[str]:
    return line.split(",")
''',
    "parsers/__init__.py": "",
    "parsers/json_reader.py": filler("json reader", "load json records with a schema check"),
    "parsers/ini_reader.py": filler("ini reader", "read sections and keys from ini files"),
    "parsers/quotes.py": '''"""Smart quotes -> plain quotes in text fields."""


def plain_quotes(text: str) -> str:
    return text.replace("\\u201c", '"').replace("\\u201d", '"')
''',
    "report.py": '''"""Summary of a CSV file: number of rows and columns."""

from io_utils.csv_reader import read_rows


def shape(text: str) -> tuple[int, int]:
    rows = read_rows(text)
    return len(rows), max((len(r) for r in rows), default=0)
''',
    "cli.py": filler("cli", "command line entry point for the converters"),
    "convert.py": filler("convert", "convert between csv, tsv and json"),
    "validate.py": filler("validate", "check that every row has the same number of fields"),
    "tests/__init__.py": "",
    "tests/test_writer.py": '''import unittest

from io_utils.csv_writer import write_line


class WriterTest(unittest.TestCase):
    def test_quotes(self):
        self.assertEqual(write_line(["a", "b,c"]), 'a,"b,c"')
''',
}
write("d3_csv_quotes", {
    "kind": "bugfix", "decoy": True,
    "objective": 'Bug report: when reading a CSV line, a quoted field that contains a comma, like "Smith, John", is '
                 "split into two columns. Quoted fields must stay one field (without the quotes), and a doubled "
                 'quote "" inside a quoted field is one quote character.',
    "acceptance_criteria": ['split_line(\'1,"Smith, John",3\') == ["1", "Smith, John", "3"]',
                            'split_line(\'"say ""hi""",x\') == [\'say "hi"\', "x"]', "plain lines still split"],
    "files_to_edit": ["io_utils/csv_reader.py"]}, D3, {"test_d3_csv_quotes.py": '''import unittest

from io_utils.csv_reader import split_line
from report import shape


class QuotesTest(unittest.TestCase):
    def test_quoted_comma(self):
        self.assertEqual(split_line('1,"Smith, John",3'), ["1", "Smith, John", "3"])

    def test_doubled_quote(self):
        self.assertEqual(split_line('"say ""hi""",x'), ['say "hi"', "x"])

    def test_plain(self):
        self.assertEqual(split_line("a, b,c"), ["a", "b", "c"])
        self.assertEqual(shape('a,"b,c"\\nd,e\\n'), (2, 2))


if __name__ == "__main__":
    unittest.main()
'''}, edits(("io_utils/csv_reader.py", '''    return [field.strip() for field in line.rstrip("\\n").split(",")]
''', '''    fields: list[str] = []
    current: list[str] = []
    quoted = False
    text = line.rstrip("\\n")
    i = 0
    while i < len(text):
        ch = text[i]
        if quoted:
            if ch == '"' and text[i + 1:i + 2] == '"':
                current.append('"')
                i += 1
            elif ch == '"':
                quoted = False
            else:
                current.append(ch)
        elif ch == '"':
            quoted = True
        elif ch == ",":
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    fields.append("".join(current).strip())
    return fields
''')))

print("built: x1_tcp_nick x2_cli_top_words x3_pkg_inventory d1_discount_percent d2_session_minutes d3_csv_quotes")
