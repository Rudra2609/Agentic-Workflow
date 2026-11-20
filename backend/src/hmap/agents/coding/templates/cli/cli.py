"""Command-line tool skeleton: ``main(argv)`` parses arguments, runs one subcommand and returns an exit code.

    python cli.py count notes.txt          # lines / words / characters of a file
    echo "a b" | python cli.py count -     # "-" reads stdin
"""

import argparse
import sys
from collections.abc import Sequence


def count(text: str) -> dict[str, int]:
    return {"lines": len(text.splitlines()), "words": len(text.split()), "chars": len(text)}


def read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli", description="command-line tool")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("count", help="count lines, words and characters")
    p.add_argument("path", help="a file, or - for stdin")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "count":
            result = count(read_input(args.path))
            print(" ".join(f"{k}={v}" for k, v in result.items()))
            return 0
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
