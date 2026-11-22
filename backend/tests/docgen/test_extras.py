"""Sprint 9 stretch items: JavaScript inspector, architecture SVG, docs-as-site HTML, changelog for docs.update,
docstring write-back patch."""

import ast
import xml.etree.ElementTree as ET

from hmap.agents.docgen import architecture, export
from hmap.agents.docgen.grounding import rule_claims
from hmap.agents.docgen.inspect import inspect_files
from hmap.agents.docgen.summarize import SymbolSummary
from tests.docgen.conftest import repo_facts, repo_files

JS = {"package.json": '{"dependencies": {"express": "^4.19.2"}, "scripts": {"start": "node src/server.js"}}',
      "src/server.js": "// app.get('/old')\nconst express = require('express');\nconst { add } = require('./store');\n"
                       "const app = express();\nconst PORT = process.env.PORT || 3000;\n"
                       "app.get('/items', (req, res) => res.json([]));\n"
                       "app.post('/items', (req, res) => res.json(add(req.body)));\n"
                       "app.listen(PORT);\n",
      "src/store.js": "export function add(item) { return item; }\nexport class ItemStore {}\n",
      "test/store.test.js": "import { add } from '../src/store.js';\ntest('adds', () => {});\n"}


def test_javascript_inspector() -> None:
    f = inspect_files(JS, "shop")
    assert f.language == "javascript" and f.ports == [3000] and set(f.env) == {"PORT"}
    assert [(r.method, r.path) for r in f.routes] == [("GET", "/items"), ("POST", "/items")]   # not the comment
    assert f.tests == ["test/store.test.js"] and f.test_functions == 1
    assert f.modules["src/server.js"].local_imports == ["src/store.js"]
    assert {"add", "ItemStore"} <= f.symbol_names()
    bad = {c.text for c in rule_claims("An Express API: GET /items, DELETE /items/1, `npm run dev`. `ItemStore` "
                                       "keeps them in Redis.", f) if c.verdict == "ungrounded"}
    assert bad == {"DELETE /items/1", "npm run dev", "Redis"}


def test_svg_is_valid_and_escapes_labels() -> None:
    graph = architecture.extract(repo_facts("tcp_chat")).graph()
    graph["nodes"].append({"id": "x", "label": "<script>alert(1)</script>", "kind": "library"})
    text = export.svg(graph, "t")
    root = ET.fromstring(text)
    assert root.tag.endswith("svg") and "<script>" not in text and "&lt;script&gt;" in text
    assert len([e for e in root.iter() if e.tag.endswith("rect")]) == len(graph["nodes"]) + 1   # + background


def test_site_escapes_everything() -> None:
    page = export.site({"readme": "# T\n\n<img src=x onerror=alert(1)> and [x](javascript:alert(1))\n\n"
                                  "| a | b |\n|---|---|\n| `c` | **d** |\n\n```bash\nmake <x>\n```\n",
                        "api": "## API\n- one\n- two\n", "architecture": "## A\n"}, "Docs", "<svg></svg>")
    assert "<img" not in page and "&lt;img" in page and 'href="javascript' not in page
    assert "<table>" in page and "<code>c</code>" in page and "<strong>d</strong>" in page
    assert "make &lt;x&gt;" in page and '<a href="#doc-api">API</a>' in page and "<svg></svg>" in page


def test_changelog() -> None:
    old = repo_facts("todo_api")
    files = repo_files("todo_api")
    files["app.py"] += '\n\n@app.get("/stats")\ndef stats() -> dict:\n    return {}\n'
    files["extra.py"] = "import os\nX = os.environ.get('TODO_MODE', 'a')\n"
    files["cli.py"] = "import argparse\np = argparse.ArgumentParser()\np.add_argument('--limit')\np.parse_args()\n"
    log = export.changelog(old, inspect_files(files, "todo_api"))
    assert "Added endpoints: `GET /stats`." in log and "Added environment variables: `TODO_MODE`." in log
    assert "Added modules: `cli.py`, `extra.py`." in log
    assert "Added command-line options: `--limit` (cli.py)." in log
    assert export.changelog(old, old) == []


def test_docstring_patch_applies_and_parses() -> None:
    files = repo_files("todo_api")
    undocumented = next(s.name for p, s in repo_facts("todo_api").public_symbols()
                        if p == "storage.py" and not s.doc and s.kind == "function")
    patch = export.docstring_patch(files, [SymbolSummary(path="storage.py", name=undocumented, kind="function",
                                                         summary="Does the thing.", by="model")])
    assert patch.startswith("--- a/storage.py") and '+    """Does the thing."""' in patch
    lines = files["storage.py"].split("\n")             # apply by hand: insert the + line at its place
    new = [ln[1:] for ln in patch.splitlines()[3:] if not ln.startswith(("-", "@@"))]
    assert '    """Does the thing."""' in new
    ast.parse("\n".join(lines))
    assert export.docstring_patch(files, []) == ""
