"""Items 10.2 / 10.10: the deterministic layer on the 36-pair calibration set reproduces the prototype (accuracy,
Cohen's kappa, the two misses that need a model), and the bias probes (padded producer note, reversed evidence)
change no verdict."""

import copy
from collections import Counter

from hmap.agents.review import checks
from hmap.agents.review.model import DeliverableEv, Evidence, Item, TestEv
from tests.review.helpers import calibration, item_of, rules_verdict

FILLER = (" This implementation is complete, robust and production ready, follows industry best practice, and has"
          " been carefully reviewed; every edge case is handled.")


def kappa(gold: list[str], pred: list[str]) -> float:
    n = len(gold)
    observed = sum(g == p for g, p in zip(gold, pred, strict=True)) / n
    cg, cp = Counter(gold), Counter(pred)
    expected = sum(cg[x] * cp[x] for x in ("PASS", "PARTIAL", "FAIL")) / (n * n)
    return (observed - expected) / (1 - expected)


def test_calibration_set_matches_the_prototype() -> None:
    items = calibration()
    assert len(items) >= 30
    gold = [i["label"] for i in items]
    pred = [rules_verdict(item_of(i)) for i in items]
    assert kappa(gold, pred) >= 0.9
    misses = {i["id"] for i, p in zip(items, pred, strict=True) if p != i["label"]}
    assert misses == {"C14", "C31"}        # a never-implemented requirement; a report section with no reasons


def test_bias_probes_flip_nothing() -> None:
    for raw in calibration():
        base = rules_verdict(item_of(raw))
        padded = copy.deepcopy(raw)
        padded["evidence"]["producer_note"] += FILLER
        reordered = copy.deepcopy(raw)
        for key in ("deliverables", "tests", "verification", "doc_ungrounded"):
            reordered["evidence"][key].reverse()
        assert rules_verdict(item_of(padded)) == base
        assert rules_verdict(item_of(reordered)) == base


def test_order_of_the_checks() -> None:
    stub = Item(id="R1", text="x", evidence=Evidence(stub=True, tests=[TestEv(name="t", status="failed",
                                                                               covers=["R1"])]))
    c = checks.run(stub)
    assert c.verdict == "PARTIAL" and c.no_action               # stub output is never revised
    missing = Item(id="D1", kind="deliverable", text="README", evidence=Evidence(
        deliverables=[DeliverableEv(name="README", present=False)],
        tests=[TestEv(name="t", status="passed", covers=["D1"])]))
    assert checks.run(missing).category == "MISSING"
    half = Item(id="R2", text="x", evidence=Evidence(tests=[TestEv(name="a", status="passed", covers=["R2"]),
                                                            TestEv(name="b", status="failed", covers=["R2"],
                                                                   module="client.py")]))
    c = checks.run(half)
    assert (c.verdict, c.category, c.module) == ("PARTIAL", "INCORRECT", "client.py")
    nothing = Item(id="R3", text="x")
    assert checks.run(nothing).verdict == "UNDECIDED"
    violated = Item(id="C1", kind="constraint", text="Do not use asyncio",
                    evidence=Evidence(violations=["uses asyncio: server.py import(s) it"]))
    assert checks.run(violated).verdict == "FAIL"
    doc = Item(id="R4", text="x", mode="document", evidence=Evidence(doc_status="not shown"))
    assert (checks.run(doc).verdict, checks.run(doc).category) == ("FAIL", "MISSING")
