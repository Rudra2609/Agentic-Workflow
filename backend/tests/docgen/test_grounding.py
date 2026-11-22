"""Item 9.6: the grounding checker. Rules: no false alarm on the hand-written READMEs, every seeded false claim
caught (the prototype's 31/31), commands of every tool; the model layer for behaviour claims (FakeLLM); the final
gate that removes ungrounded sentences."""

import pytest

from hmap.agents.docgen.grounding import behaviour, check_documents, remove_sentences, rule_claims
from hmap.agents.docgen.grounding.rules import Checker, version_ok
from hmap.agents.docgen.inspect import inspect_files
from hmap.core.llm import FakeLLM
from tests.docgen.conftest import REPO_NAMES, SEEDED, readme_of, repo_facts, repo_files


@pytest.mark.parametrize("name", REPO_NAMES)
def test_hand_written_readmes_have_no_false_alarm(name: str) -> None:
    claims = rule_claims(readme_of(name), repo_facts(name), "readme")
    assert len(claims) >= 15
    assert [c for c in claims if c.verdict == "ungrounded"] == []


@pytest.mark.parametrize("seed", [s for s in SEEDED if s["expect"]], ids=lambda s: s["id"])
def test_seeded_false_claim_is_caught(seed: dict[str, str]) -> None:
    doc = readme_of(seed["repo"]).rstrip() + "\n\n" + seed["sentence"] + "\n"
    bad = [c for c in rule_claims(doc, repo_facts(seed["repo"])) if c.verdict == "ungrounded"]
    assert any(seed["expect"] in c.text for c in bad), [(c.kind, c.text) for c in bad]


def test_behaviour_claims_are_out_of_reach_for_rules() -> None:
    for seed in (s for s in SEEDED if not s["expect"]):
        doc = readme_of(seed["repo"]).rstrip() + "\n\n" + seed["sentence"] + "\n"
        assert not [c for c in rule_claims(doc, repo_facts(seed["repo"])) if c.verdict == "ungrounded"]


def test_negation_line_numbers_and_sentences() -> None:
    f = repo_facts("tcp_chat")
    claims = rule_claims("# x\n\nThe server does not need Docker or Redis.\n\nIt caches in Redis.\n", f, "readme")
    bad = [c for c in claims if c.verdict == "ungrounded"]
    assert [(c.text, c.line, c.sentence) for c in bad] == [("Redis", 5, "It caches in Redis.")]


def test_commands_of_many_tools() -> None:
    files = {"Makefile": "demo:\n\techo hi\ntest:\n\tpytest\n", "package.json": '{"scripts": {"build": "next"}}',
             "pyproject.toml": '[project]\nname="x"\ndependencies=["fastapi==0.115.6", "uvicorn"]\n'
                               '[project.scripts]\nx-run = "app:main"\n',
             "app.py": "import os\nfrom fastapi import FastAPI\napp = FastAPI()\n"
                       "PORT = int(os.getenv('X_PORT', '8000'))\n@app.get('/items')\ndef items(): ...\n",
             "scripts/go.sh": "echo\n"}
    c = Checker(inspect_files(files, "x"))
    ok = ["make demo", "make test", "npm run build", "npm ci", "x-run", "uv run x-run", "scripts/go.sh",
          "curl http://localhost:8000/items", "X_PORT=9 make demo", "uvicorn app:app", "pip install fastapi"]
    bad = ["make deploy", "npm run lint", "scripts/nope.sh", "curl -X POST http://localhost:8000/items",
           "curl http://localhost:9999/items", "NOPE=1 make demo", "pip install redis", "python -m nothing_here"]
    assert [x for x in ok if not c.command(x).grounded] == []
    assert [x for x in bad if c.command(x).grounded] == []
    assert c.command("brew install foo").verdict == "unchecked"
    assert version_ok("0.115", "==0.115.6")[0] and not version_ok("0.99", "==0.115.6")[0]
    assert version_ok("18.3", "^18.3.1")[0]


def test_citations_and_module_names() -> None:
    c = Checker(repo_facts("tcp_chat"))
    assert c.span("server.py::Room")[0].grounded
    assert not c.span("server.py::nothing")[0].grounded
    assert not c.span("nope.py::Room")[0].grounded


def test_remove_sentences_keeps_the_rest() -> None:
    f = repo_facts("tcp_chat")
    md = "# t\n\nThe server uses threads. It caches in Redis.\n\n| a | Kafka queue |\n\nEnd.\n"
    bad = [c for c in rule_claims(md, f, "readme") if c.verdict == "ungrounded"]
    out, removed = remove_sentences(md, bad)
    assert "Redis" not in out and "Kafka" not in out and "The server uses threads." in out and "End." in out
    assert len(removed) == 2


async def test_behaviour_layer_with_a_model() -> None:
    files = repo_files("tcp_chat")
    quote = next(line.strip() for line in files["server.py"].splitlines() if "lower()" in line or "nick" in line)
    fake = FakeLLM(default=None).on_schema(behaviour._Verdicts, behaviour._Verdicts(verdicts=[
        behaviour._Verdict(id=1, verdict="SUPPORTED", quote=quote),
        behaviour._Verdict(id=2, verdict="CONTRADICTED", quote="this line is not in the code at all"),
        behaviour._Verdict(id=3, verdict="CONTRADICTED", quote=quote)]))
    md = ("# chat\n\nThe server keeps a nickname for every client that joins the room.\n"
          "The server stores every message on disk for a week.\nThe server rejects nicknames that are taken.\n")
    acc, stats = await check_documents({"readme": md}, repo_facts("tcp_chat"), files, fake)
    model = [c for c in acc.claims if c.by == "model"]
    assert [c.verdict for c in model] == ["grounded", "unverified", "ungrounded"]   # invented quote -> unverified
    assert stats["model_calls"] == 1


async def test_behaviour_layer_without_a_model_is_skipped() -> None:
    md = "# chat\n\nThe server keeps a nickname for every client that joins the room.\n"
    acc, stats = await check_documents({"readme": md}, repo_facts("tcp_chat"), repo_files("tcp_chat"),
                                       FakeLLM(default=None))
    assert not [c for c in acc.claims if c.by == "model"]
    assert "model not available" in str(stats["behaviour"])


def test_grounded_pct_counts_removed_claims() -> None:
    from hmap.agents.docgen.grounding import summarize
    claims = rule_claims("Uses threads. Uses Redis.\n", repo_facts("tcp_chat"))
    good = [c for c in claims if c.grounded]
    acc = summarize(good, [c for c in claims if not c.grounded])
    assert acc.checked == 2 and acc.grounded_pct == 50.0 and acc.ungrounded == 0


def test_quoted_requirements_are_not_claims() -> None:
    f = repo_facts("tcp_chat")
    md = "| R9: “The server must listen on port 5050 and cache in Redis” | not shown |\nIt uses Redis.\n"
    bad = [c for c in rule_claims(md, f) if c.verdict == "ungrounded"]
    assert [(c.text, c.line) for c in bad] == [("Redis", 2)]


def test_rules_found_by_the_model_written_readmes() -> None:
    """Misses and false flags found by labelling the model-written READMEs (eval.md §3.4)."""
    todo = Checker(repo_facts("todo_api"))
    assert todo.command("curl http://localhost:8000/todos/1").grounded            # a value for {todo_id}
    assert not todo.command("curl -X PUT http://localhost:8000/todos/1").grounded
    assert todo.command("pip install .[dev]").grounded and todo.command("pip install .").grounded
    assert todo.command("pip install pytest").grounded                          # a dev tool, not a code claim
    assert todo.command("cd todo-api").verdict == "unchecked"                  # the folder a clone makes
    assert not todo.command("cd src/nothing").grounded
    assert not todo.span("LICENSE")[0].grounded                                 # a conventional file that is missing
    assert todo.span("ValueError")[0].grounded and todo.span("str.isalnum()")[0].grounded
    b2 = Checker(repo_facts("tcp_chat"))
    assert not b2.command("python -m server --host 0.0.0.0").grounded           # server.py has no options
    assert not b2.command("pip install -e .").grounded
    assert "no pyproject.toml" in b2.command("pip install -e .").why
    md = "# x\n\n1. Install\n   ```bash\n   pip install redis\n   ```\n\n```bash\ncurl -X POST \\\n  http://localhost:5050/x\n```\n"
    bad = {c.text for c in rule_claims(md, repo_facts("tcp_chat")) if c.verdict == "ungrounded"}
    assert "pip install redis" in bad                                           # an indented fence is read
    assert any(t.startswith("curl -X POST") for t in bad)                       # continuation lines joined
