"""Command line: summarize the numeric columns of a CSV file."""

import argparse
from pathlib import Path

import render
import stats


def render_summary(summary: dict, fmt: str) -> str:
    if fmt == "md":
        return render.to_markdown(summary)
    return render.to_html(summary)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Summarize the numeric columns of a CSV file.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--format", choices=["md", "html"], default="md")
    args = parser.parse_args(argv)
    print(render_summary(stats.summarize(stats.load(args.input)), args.format), end="")


if __name__ == "__main__":
    main()
