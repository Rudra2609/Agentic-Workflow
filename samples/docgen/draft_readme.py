#!/usr/bin/env python3
"""Facts-first README draft (Member 9, prepared ahead of Sprint 9 item 9.4): every technical line comes from
``inspect_repo.py``'s facts, so it is grounded by construction. A model only writes the prose paragraph later (marked
``<!-- prose -->``), and the grounding checker then checks that paragraph too. Plain Python 3.11.

    python3 samples/docgen/draft_readme.py samples/docgen/repos/todo_api
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_repo import inspect, mermaid  # noqa: E402


def draft(facts: dict) -> str:
    out = [f"# {facts['repo']}", "", "<!-- prose: one paragraph written by the model from the facts below -->", ""]
    if facts["python_requires"]:
        out += [f"Requires Python {facts['python_requires'].lstrip('>=~= ')} (`requires-python {facts['python_requires']}`).",
                ""]
    out += ["## Run", "```bash"]
    if "pyproject.toml" in facts["files"]:
        out.append('pip install -e ".[' + ",".join(facts["extras"]) + ']"' if facts["extras"] else "pip install -e .")
    elif "requirements.txt" in facts["files"]:
        out.append("pip install -r requirements.txt")
    for entry in facts["entrypoints"]:
        required = [f for f in facts["cli"].get(entry, {}) if f in ("--input", "--nick")]  # a sample value is needed
        out.append(f"python {entry}" + "".join(f" {flag} VALUE" for flag in required))
    out += ["```", ""]
    for script, flags in facts["cli"].items():
        out += [f"`{script}` options: " + ", ".join(f"`{f}`" + (f" ({' / '.join(c)})" if c else "")
                                                     for f, c in flags.items()), ""]
    if facts["env"]:
        out += ["## Configuration", "| Variable | Default |", "|---|---|"]
        out += [f"| `{name}` | {default if default is not None else '(required)'} |"
                for name, default in facts["env"].items()]
        out.append("")
    if facts["ports"]:
        out += ["Listens on " + " and ".join(f"port {p}" for p in facts["ports"]) + ".", ""]
    if facts["routes"]:
        out += ["## Endpoints", "| Endpoint | Defined in |", "|---|---|"]
        out += [f"| {r['method']} {r['path']} | `{r['file']}` |" for r in facts["routes"]]
        out.append("")
    out += ["## Code", "```mermaid", mermaid(facts).rstrip(), "```", ""]
    for rel, mod in facts["modules"].items():
        if not rel.startswith("tests/"):
            names = [f"`{f}()`" for f in mod["functions"] if not f.startswith("_")][:8]
            out.append(f"- `{rel}`" + (": " + ", ".join(names) if names else ""))
    if facts["tests"]:
        out += ["", "## Tests", "```bash", "pytest", "```", f"{len(facts['tests'])} test file(s): "
                + ", ".join(f"`{t}`" for t in facts["tests"]) + "."]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(draft(inspect(Path(sys.argv[1]))), end="")
