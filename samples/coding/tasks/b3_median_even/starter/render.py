"""Turn a summary into Markdown or HTML."""

import html


def to_markdown(summary: dict[str, dict[str, float]]) -> str:
    lines = ["| column | min | max | mean | median |", "|---|---|---|---|---|"]
    for column, s in summary.items():
        lines.append(f"| {column} | {s['min']:g} | {s['max']:g} | {s['mean']:.2f} | {s['median']:g} |")
    return "\n".join(lines) + "\n"


def to_html(summary: dict[str, dict[str, float]]) -> str:
    rows = "".join(f"<tr><td>{html.escape(c)}</td><td>{s['mean']:.2f}</td></tr>" for c, s in summary.items())
    return f"<table><tr><th>column</th><th>mean</th></tr>{rows}</table>\n"
