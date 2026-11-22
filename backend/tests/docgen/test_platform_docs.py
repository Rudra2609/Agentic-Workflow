"""Item 9.19: the platform documents in docs/members/9/platform/ stay grounded in the platform's code (the generated
ones were checked when they were made; the hand-written runbook and troubleshooting guide are checked here)."""


import pytest

from hmap.agents.docgen.grounding import rule_claims
from hmap.agents.docgen.inspect import inspect_files
from tests.docgen.conftest import ROOT
from tests.docgen.eval.run_eval import platform_files, platform_listing

PLATFORM = ROOT / "docs" / "members" / "9" / "platform"


@pytest.fixture(scope="module")
def facts():  # type: ignore[no-untyped-def]
    """The same facts the agent used: the platform's routes from its own OpenAPI document (trusted code)."""
    from hmap.agents.docgen.api_docs import routes_from_openapi
    from hmap.api.app import create_app

    f = inspect_files(platform_files(), "hmap", platform_listing())
    f.routes = routes_from_openapi(create_app().openapi(), f.routes)
    return f


@pytest.mark.parametrize("name", ["runbook.md", "troubleshooting.md", "README.md", "architecture.md", "api.md"])
def test_platform_document_is_grounded(name: str, facts) -> None:  # type: ignore[no-untyped-def]
    path = PLATFORM / name
    if not path.is_file():
        pytest.skip(f"{name} not generated yet")
    claims = rule_claims(path.read_text(encoding="utf-8"), facts, name)
    assert len([c for c in claims if c.verdict == "grounded"]) >= 10
    bad = [(c.kind, c.text, c.why) for c in claims if c.verdict == "ungrounded"]
    assert bad == []


def test_injected_mistake_in_the_runbook_is_caught(facts) -> None:  # type: ignore[no-untyped-def]
    text = (PLATFORM / "runbook.md").read_text(encoding="utf-8") + "\nRun `make deploy`, then open port 8080.\n"
    bad = {c.text for c in rule_claims(text, facts) if c.verdict == "ungrounded"}
    assert bad == {"make deploy", "port 8080"}


def test_scripts_settings_are_facts(facts) -> None:  # type: ignore[no-untyped-def]
    assert {"HMAP_DEMO_NO_OPEN", "HMAP_DEMO_SKIP_PREFLIGHT", "HMAP_DEMO_MIN_FREE_GB"} <= set(facts.env)
