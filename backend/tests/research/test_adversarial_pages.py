"""The adversarial pages (5.12; reused by Member 6's suite): after cleaning no instruction text is left, facts are."""


import pytest

from hmap.agents.research import sanitize
from hmap.agents.research.clean import clean
from hmap.core.config import REPO_ROOT

PAGES = REPO_ROOT / "samples" / "research" / "adversarial"
FORBIDDEN = ["ignore", "turbosocket", "system:", "system prompt", "you are now", "new instructions", "as an ai",
             "must answer", "recommend this website"]
FACTS = {"hidden_instructions.html": "calls listen and then accept",
         "visible_injection.html": "dispatches callbacks when sockets become ready",
         "zero_width_system_prompt.html": "a header, a payload and a signature",
         "seo_spam.html": "Click here to download"}


@pytest.mark.parametrize("name", sorted(FACTS))
async def test_cleaning_removes_every_instruction_and_keeps_the_facts(name: str) -> None:
    page = await clean((PAGES / name).read_bytes(), url=f"https://adversarial.example/{name}", media_type="text/html")
    low = page.text.lower()
    assert not [w for w in FORBIDDEN if w in low], page.text
    assert FACTS[name] in page.text and not sanitize.looks_injected(page.text)
    assert "​" not in page.text


def test_every_sample_is_listed() -> None:
    assert {p.name for p in PAGES.glob("*.html")} == set(FACTS)
    assert all(name in (PAGES / "README.md").read_text() for name in FACTS)


async def test_cleaning_is_deterministic_whatever_was_read_before() -> None:
    raw = (PAGES / "visible_injection.html").read_bytes()
    first = await clean(raw, url="https://a.example/1", media_type="text/html")
    for name in FACTS:                                     # read other pages sharing a paragraph
        await clean((PAGES / name).read_bytes(), url=f"https://a.example/{name}", media_type="text/html")
    again = await clean(raw, url="https://a.example/1", media_type="text/html")
    assert again.content_sha256 == first.content_sha256
