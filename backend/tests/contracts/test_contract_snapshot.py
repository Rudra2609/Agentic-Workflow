"""Contract snapshot: the exported JSON Schemas must match tests/contracts/snapshots/ exactly.

If this fails, the message says WHICH contract changed, WHO owns it and WHO consumes it — so a broken consumer can
point at the producing change. Breaking changes need a new major version + adapter + sign-off (research §28).
Additive changes are fine but must be accepted deliberately: `make contracts-snapshot` (so reviewers see it).
"""

import json
from pathlib import Path

import pytest

from hmap.core.contracts.export import all_schemas
from tests.contracts.compat import Change, compare, owner_of

SNAPSHOTS = Path(__file__).with_name("snapshots")


def _load_snapshots() -> dict[str, dict]:
    return {p.relative_to(SNAPSHOTS).as_posix(): json.loads(p.read_text()) for p in SNAPSHOTS.rglob("*.schema.json")}


def test_snapshot_exists() -> None:
    assert SNAPSHOTS.is_dir() and any(SNAPSHOTS.rglob("*.schema.json")), "run `make contracts-snapshot` once"


def test_contracts_unchanged_or_explicitly_accepted() -> None:
    old, new = _load_snapshots(), all_schemas()
    problems: list[str] = []
    for name in sorted(set(old) | set(new)):
        owner, consumers = owner_of(name)
        if name not in new:
            problems.append(f"BREAKING  {name}: contract removed  [owner {owner}; consumers {consumers}]")
            continue
        if name not in old:
            problems.append(f"ADDITIVE  {name}: new contract  [owner {owner}] -> accept with `make contracts-snapshot`")
            continue
        changes: list[Change] = compare(old[name], new[name])
        if not changes and old[name] != new[name]:
            changes = [Change("additive", "$", "metadata/description/default changed")]
        for c in changes:
            hint = ("needs a new major schema_version + adapter + sign-off from the consumers"
                    if c.kind == "breaking" else "accept with `make contracts-snapshot`")
            problems.append(f"{c.kind.upper():9s} {name} at {c.where}: {c.what}  "
                            f"[owner {owner}; consumers {consumers}] -> {hint}")
    if problems:
        pytest.fail("Contract changes detected:\n  " + "\n  ".join(problems), pytrace=False)


@pytest.mark.parametrize(("old", "new", "kind"), [
    ({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
     {"type": "object", "properties": {}, "required": []}, "breaking"),                       # removed
    ({"type": "object", "properties": {}}, {"type": "object", "properties": {"b": {"type": "integer"}},
                                             "required": ["b"]}, "breaking"),                  # new required
    ({"type": "object", "properties": {}}, {"type": "object", "properties": {"b": {"type": "integer"}}},
     "additive"),                                                                               # new optional
    ({"type": "object", "properties": {"a": {"type": "string"}}},
     {"type": "object", "properties": {"a": {"type": "integer"}}}, "breaking"),                # type change
    ({"type": "object", "properties": {"s": {"enum": ["x", "y"], "type": "string"}}},
     {"type": "object", "properties": {"s": {"enum": ["x"], "type": "string"}}}, "breaking"),  # enum removed
    ({"type": "object", "properties": {"s": {"enum": ["x"], "type": "string"}}},
     {"type": "object", "properties": {"s": {"enum": ["x", "z"], "type": "string"}}}, "additive"),
    ({"$defs": {"T": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
      "type": "object", "properties": {"t": {"$ref": "#/$defs/T"}}},
     {"$defs": {"T": {"type": "object", "properties": {}, "required": []}},
      "type": "object", "properties": {"t": {"$ref": "#/$defs/T"}}}, "breaking"),            # nested via $ref
])
def test_compat_checker_classifies(old, new, kind) -> None:
    changes = compare(old, new)
    assert changes and {c.kind for c in changes} == {kind}


def test_owner_attribution() -> None:
    assert owner_of("domain/TaskGraph.schema.json")[0] == "Member 3"
    assert owner_of("messages/task.assign.schema.json")[0] == "Member 1"
