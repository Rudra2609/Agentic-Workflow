"""Items 9.1 / 9.2: the facts extractor (same facts as the prototype on its repos, more on the platform) and the
architecture extractor (valid Mermaid, every edge an import, folding, detail diagrams)."""

import json
from pathlib import Path

import pytest

from hmap.agents.docgen import architecture as A
from hmap.agents.docgen.inspect import inspect_files, read_tree
from tests.docgen.conftest import REPO_NAMES, ROOT, SAMPLES, repo_facts


@pytest.mark.parametrize("name", REPO_NAMES)
def test_facts_match_the_prototype(name: str) -> None:
    old = json.loads((SAMPLES / "out" / name / "facts.json").read_text())
    f = repo_facts(name)
    assert {(r.method, r.path) for r in f.routes} == {(r["method"], r["path"]) for r in old["routes"]}
    assert set(f.env) == set(old["env"])
    assert f.ports == old["ports"]
    assert f.cli == old["cli"]
    assert f.dependencies == old["dependencies"]
    assert f.tests == old["tests"]
    assert f.entrypoints == old["entrypoints"]


def test_required_flags_and_test_functions() -> None:
    assert repo_facts("tcp_chat").cli_required == {"client.py": ["--nick"]}
    assert repo_facts("csv_report").cli_required["report.py"] == ["--input"]
    assert repo_facts("todo_api").test_functions >= 1


def test_router_prefixes_settings_and_click() -> None:
    files = {
        "app/__init__.py": "",
        "app/main.py": "from fastapi import FastAPI\nfrom app.routers import items\napp = FastAPI()\n"
                       "app.include_router(items.router, prefix='/api')\n",
        "app/routers/__init__.py": "",
        "app/routers/items.py": "from fastapi import APIRouter\nrouter = APIRouter(prefix='/items')\n"
                                "@router.get('/{item_id}')\ndef read(item_id: int): ...\n"
                                "@router.post('')\ndef create(): ...\n",
        "app/config.py": "from pydantic_settings import BaseSettings, SettingsConfigDict\n"
                         "class S(BaseSettings):\n    model_config = SettingsConfigDict(env_prefix='SHOP_')\n"
                         "    db_url: str = 'sqlite:///x.db'\n    debug: bool = False\n",
        "cli.py": "import click\n@click.command()\n@click.option('--mode', type=click.Choice(['a', 'b']))\n"
                  "def main(mode): ...\n",
        "settings.py": "def load(e):\n    m = {'APP_HOST': 'host', 'APP_PORT': 'port', 'APP_MODE': 'mode'}\n"
                       "    for key, field in (('APP_DEBUG', 'debug'),):\n        pass\n    return get('APP_TOKEN')\n",
    }
    f = inspect_files(files, "shop")
    assert {(r.method, r.path) for r in f.routes} == {("GET", "/api/items/{item_id}"), ("POST", "/api/items")}
    assert {"SHOP_DB_URL", "SHOP_DEBUG", "APP_HOST", "APP_PORT", "APP_MODE", "APP_DEBUG", "APP_TOKEN"} <= set(f.env)
    assert f.cli["cli.py"] == {"--mode": ["a", "b"]}
    assert f.modules["app/routers/items.py"].module == "app.routers.items"
    assert "app/routers/items.py" in f.modules["app/main.py"].local_imports


def test_the_platform_backend() -> None:
    f = inspect_files(read_tree(ROOT / "backend"), "backend")
    hmap_env = [e for e in f.env if e.startswith("HMAP_")]
    assert len(hmap_env) >= 80, len(hmap_env)          # the prototype found 5 (research §8)
    assert len(f.routes) >= 59
    assert "fastapi" in f.dependencies and f.python_requires
    assert "hmap-agents" in f.scripts


def test_read_tree_never_reads_env_files(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("HMAP_GROQ_API_KEYS=secret\n")
    (tmp_path / ".env.example").write_text("HMAP_X=1\n")
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "b.js").write_text("x")
    assert sorted(read_tree(tmp_path)) == [".env.example", "a.py"]


@pytest.mark.parametrize("name", REPO_NAMES)
def test_mermaid_is_valid_and_every_edge_is_an_import(name: str) -> None:
    f = repo_facts(name)
    arch = A.extract(f)
    text = A.mermaid(arch)
    nodes, edges = A.parse_mermaid(text)
    assert {c.id for c in arch.components} <= nodes
    assert A.check_edges(text, arch, f) == []
    assert ("server", "protocol", "-->") in edges if name == "tcp_chat" else True


def test_a_made_up_edge_is_caught() -> None:
    f = repo_facts("tcp_chat")
    arch = A.extract(f)
    bad = A.mermaid(arch).replace("  server --> protocol\n", "  server --> protocol\n  protocol --> client\n")
    assert A.check_edges(bad, arch, f) == ["protocol --> client"]
    with pytest.raises(ValueError):
        A.parse_mermaid("flowchart LR\n  a --> b\n")        # undeclared nodes
    with pytest.raises(ValueError):
        A.parse_mermaid("flowchart LR\n  a[\"x\"]\n  click a callback\n")


def test_the_platform_folds_into_packages_with_detail_diagrams() -> None:
    f = inspect_files(read_tree(ROOT / "backend"), "backend")
    arch = A.extract(f)
    labels = {c.label for c in arch.components}
    assert len(arch.components) <= A.MAX_NODES and arch.folded
    assert {"hmap.agents", "hmap.core", "hmap.manager"} <= labels
    assert not any("coding/templates/" in m and not m.endswith("templates/__init__.py")       # templates = data
                   for c in arch.components for m in c.modules)
    assert A.check_edges(A.mermaid(arch), arch, f) == []
    details = A.details(f, arch)
    assert "hmap.agents" in details and len(details["hmap.agents"].components) >= 8
    for d in details.values():
        assert A.check_edges(A.mermaid(d, externals=False), d, f) == []
    doc = A.render_doc(f, arch, details, "Narrative.")
    assert doc.count("```mermaid") == 1 + sum(len(d.components) >= 2 for d in details.values())
