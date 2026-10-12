def markdown_table(rows, columns=None):
    if columns is None:
        if not rows:
            return ""
        columns = list(rows[0].keys())
    if not columns:
        return ""
    esc = lambda v: str(v).replace("|", "\\|")
    lines = ["| " + " | ".join(esc(c) for c in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(esc(r[c]) if c in r else "" for c in columns) + " |")
    return "\n".join(lines)
