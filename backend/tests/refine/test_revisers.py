"""Revisers (item 4.4): JSON patches, targeted (unflagged parts stay byte-identical), full rewrite, schema, dispatch."""

import json

import pytest
from pydantic import BaseModel

from hmap.agents.refine import FullRewriteReviser, SchemaReviser, StrategicReviser, TargetedReviser
from hmap.agents.refine.core import Critique, RefineContext
from hmap.agents.refine.revisers import Patch, PatchError, apply, apply_all, resolve, within
from hmap.agents.refine.revisers.patch import canonical_bytes
from hmap.agents.refine.revisers.targeted import PatchAnswer
from hmap.core.llm import FakeLLM
from tests.refine.conftest import CountingReviser, issue

DOC = {"title": "Plan", "items": [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}],
       "meta": {"owner": "x", "tags": ["t1", "t2"]}}


def test_patch_apply_add_replace_remove_and_errors() -> None:
    out = apply_all(DOC, [Patch("replace", "/items/1/text", "TWO"), Patch("add", "/items/-", {"id": "c"}),
                          Patch("remove", "/meta/owner"), Patch("add", "/meta/tags/0", "t0")])
    assert out["items"][1]["text"] == "TWO" and out["items"][2] == {"id": "c"}
    assert "owner" not in out["meta"] and out["meta"]["tags"] == ["t0", "t1", "t2"]
    assert DOC["items"][1]["text"] == "two" and DOC["meta"]["owner"] == "x"      # input untouched
    assert resolve(out, "/items/0/id") == "a"
    for bad in (Patch("replace", "/nope", 1), Patch("remove", "/items/9"), Patch("replace", "items", 1),
                Patch("remove", "")):
        with pytest.raises(PatchError):
            apply(DOC, bad)
    assert within("/items/1/text", "/items/1") and within("/items/-", "/items") and not within("/itemsX", "/items")


def test_patch_leaves_untouched_subtrees_identical() -> None:
    out = apply(DOC, Patch("replace", "/items/0/text", "ONE"))
    assert out["items"][1] is DOC["items"][1] and out["meta"] is DOC["meta"]
    assert canonical_bytes(out["meta"]) == canonical_bytes(DOC["meta"])


async def test_targeted_reviser_applies_only_patches_inside_flagged_locations() -> None:
    fake = FakeLLM().on_schema(PatchAnswer, {"patches": [
        {"op": "replace", "path": "/items/1/text", "value_json": json.dumps("TWO"), "issue": 1},
        {"op": "replace", "path": "/title", "value_json": json.dumps("Hacked")},          # not flagged
        {"op": "add", "path": "/items/-", "value_json": json.dumps({"id": "c", "text": "three"})},
        {"op": "replace", "path": "/items/0/text", "value_json": "{not json"},
    ], "notes": "fixed b"})
    critique = Critique(score=0.5, issues=[issue("FACTUAL", "major", "/items/1"), issue("OMISSION", "major", "/items")])
    rev = await TargetedReviser().revise(DOC, critique, [], RefineContext(llm=fake))
    assert rev.output["items"][1]["text"] == "TWO" and rev.output["items"][2]["id"] == "c"
    assert rev.output["title"] == "Plan" and rev.applied == 2
    assert any("outside the flagged" in r for r in rev.rejected) and any("not JSON" in r for r in rev.rejected)
    # unflagged parts byte-identical
    assert canonical_bytes(rev.output["meta"]) == canonical_bytes(DOC["meta"])
    assert canonical_bytes(rev.output["items"][0]) == canonical_bytes(DOC["items"][0])


class Doc(BaseModel):
    title: str
    items: list[dict[str, str]]
    meta: dict[str, object]


async def test_targeted_reviser_guard_and_contract() -> None:
    fake = FakeLLM().on_schema(PatchAnswer, {"patches": [
        {"op": "replace", "path": "/items/0/text", "value_json": json.dumps("bad word")}]})
    critique = Critique(score=0.5, issues=[issue("STYLE", "minor", "/items/0")])
    guarded = TargetedReviser(guard=lambda p, doc, inp: "no bad words" if "bad" in str(p.value) else None)
    rev = await guarded.revise(DOC, critique, [], RefineContext(llm=fake))
    assert rev.output is DOC and rev.applied == 0 and "no bad words" in rev.rejected[0]
    fake2 = FakeLLM().on_schema(PatchAnswer, {"patches": [
        {"op": "replace", "path": "/items", "value_json": json.dumps("not a list")}]})
    loaded = TargetedReviser(load=Doc.model_validate)
    rev = await loaded.revise(Doc.model_validate(DOC), Critique(score=0.5, issues=[issue(location="/items")]), [],
                              RefineContext(llm=fake2))
    assert isinstance(rev.output, Doc) and rev.output.items == DOC["items"] and "contract" in rev.rejected[-1]


async def test_full_strategy_may_touch_everything() -> None:
    fake = FakeLLM().on_schema(PatchAnswer, {"patches": [
        {"op": "replace", "path": "/title", "value_json": json.dumps("Better plan")}]})
    rev = await TargetedReviser().revise(DOC, Critique(score=0.5, issues=[issue(location="/items/0")]), [],
                                         RefineContext(llm=fake), strategy="full")
    assert rev.output["title"] == "Better plan"
    assert "Earlier targeted fixes" in fake.calls[0].messages[1].content


async def test_full_rewrite_and_schema_revisers() -> None:
    new = {"title": "New", "items": [], "meta": {}}
    fake = FakeLLM().on_schema(Doc, new)
    rev = await FullRewriteReviser(Doc).revise(Doc.model_validate(DOC), Critique(score=0.2, issues=[issue()]), [],
                                               RefineContext(llm=fake))
    assert rev.output.title == "New" and rev.applied == 1
    refusing = SchemaReviser(Doc, validate=lambda d: "empty" if not d.items else None)
    rev = await refusing.revise(Doc.model_validate(DOC), Critique(score=0.2, issues=[issue()]), [],
                                RefineContext(llm=FakeLLM().on_schema(Doc, new)))
    assert rev.output.title == "Plan" and rev.applied == 0


async def test_strategic_reviser_dispatch_and_fallback() -> None:
    t, f = CountingReviser(name="t"), CountingReviser(name="f")
    s = StrategicReviser({"targeted": t, "full": f})
    await s.revise(1, Critique(score=0.1), [], RefineContext(), strategy="widen")      # no widen -> full
    await s.revise(1, Critique(score=0.1), [], RefineContext(), strategy="targeted")
    assert f.strategies == ["widen"] and t.strategies == ["targeted"]
    rev = await s.revise(1, Critique(score=0.1), [], RefineContext(), strategy="full")
    assert rev.notes[0].startswith("strategy: full")
    with pytest.raises(ValueError):
        StrategicReviser({"full": f})
