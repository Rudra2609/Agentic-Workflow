"""Command-line entry point: summarize the numeric columns of a CSV file."""

import argparse
from pathlib import Path

import render
import stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize the numeric columns of a CSV file.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=["md", "html"], default="md")
    args = parser.parse_args()
    summary = stats.summarize(stats.load(args.input))
    text = render.to_markdown(summary) if args.format == "md" else render.to_html(summary)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
