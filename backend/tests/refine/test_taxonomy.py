"""Error taxonomy (item 4.7): rules first, ``classify`` for the rest; accuracy on the labelled set."""

import json

from hmap.agents.refine.core import CATEGORIES, RefineContext
from hmap.agents.refine.taxonomy import CODE_RULES, IssueClassifier, rule_label
from hmap.core.config import REPO_ROOT
from hmap.core.llm import FakeLLM
from tests.refine.conftest import issue

GOLD = REPO_ROOT / "samples" / "refine" / "taxonomy_gold.jsonl"


def test_gold_set_covers_every_category_and_severity() -> None:
    rows = [json.loads(line) for line in GOLD.read_text().splitlines()]
    assert len(rows) >= 80
    assert {r["label"] for r in rows} == set(CATEGORIES)
    assert {r["severity"] for r in rows} == {"info", "minor", "major", "critical"}
    assert sum(r["source"] != "hand" for r in rows) >= 25          # real critic findings, not only hand-written


def test_rules_on_the_held_out_half() -> None:
    rows = [json.loads(line) for line in GOLD.read_text().splitlines()]
    test = [r for n, r in enumerate(rows) if n % 2 == 1]            # the rules were tuned on the other half only
    labels = [rule_label(r["text"], r.get("code"))[0] for r in test]
    labelled = [(lab, r) for lab, r in zip(labels, test, strict=True) if lab is not None]
    assert len(labelled) / len(test) >= 0.8
    assert sum(lab == r["label"] for lab, r in labelled) / len(labelled) >= 0.95


def test_codes_win_over_wording() -> None:
    assert rule_label("anything at all", "cycle") == ("LOGIC", "code:cycle")
    assert all(v in CATEGORIES for v in CODE_RULES.values())
    assert rule_label("Step T5 depends only on design but needs T3's output")[0] == "LOGIC"
    assert rule_label("R9 does not appear in the assignment")[0] == "HALLUCINATION"
    assert rule_label("hello there")[0] is None


async def test_classifier_order_programmatic_rule_model_critic() -> None:
    clf = IssueClassifier()
    prog, decisions = await clf.classify([issue("SCHEMA", description="something is missing")], RefineContext(),
                                         programmatic=True)
    assert prog[0].category == "SCHEMA" and decisions[0].source == "programmatic"
    ruled, decisions = await clf.classify([issue("SAFETY", description="T5 depends on T3 but runs first")],
                                          RefineContext())
    assert ruled[0].category == "LOGIC" and decisions[0].source == "rule" and decisions[0].critic_label == "SAFETY"
    fake = FakeLLM().on_classify("category", "STYLE")
    modelled, decisions = await clf.classify([issue("OMISSION", description="hmm, odd")], RefineContext(llm=fake))
    assert modelled[0].category == "STYLE" and decisions[0].source == "classify" and len(fake.classify_calls) == 1
    kept, decisions = await clf.classify([issue("OMISSION", description="hmm, odd")], RefineContext())
    assert kept[0].category == "OMISSION" and decisions[0].source == "critic"
    assert decisions[0].as_dict()["final"] == "OMISSION"
