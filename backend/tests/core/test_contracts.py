"""Contract tests (Sprint 1 item 1.3): every example validates against its exported JSON Schema, versioning works,
and invalid messages are rejected with taxonomy errors (never raw ValidationErrors)."""

import json

import jsonschema
import pytest

from hmap.core.contracts import (
    DOMAIN_MODELS,
    PAYLOAD_MODELS,
    Envelope,
    RequirementSet,
    TaskAssign,
    TaskGraph,
    is_compatible,
    make_envelope,
    negotiate,
    parse_envelope,
)
from hmap.core.contracts import examples as ex
from hmap.core.contracts.export import all_schemas, export
from hmap.core.errors import InvalidMessage, SchemaUnsupported

SCHEMAS = all_schemas()


def _validate(schema: dict, instance: dict) -> None:
    jsonschema.Draft202012Validator(schema).validate(instance)


def test_every_message_type_has_an_example() -> None:
    assert set(ex.MESSAGE_EXAMPLES) == set(PAYLOAD_MODELS) and len(PAYLOAD_MODELS) == 15


def test_every_domain_contract_has_an_example() -> None:
    assert set(ex.DOMAIN_EXAMPLES) == set(DOMAIN_MODELS)


@pytest.mark.parametrize("mtype", sorted(PAYLOAD_MODELS))
def test_message_examples_match_exported_schema(mtype: str) -> None:
    data = ex.MESSAGE_EXAMPLES[mtype].model_dump(mode="json")
    _validate(SCHEMAS[f"messages/{mtype}.schema.json"], data)
    assert PAYLOAD_MODELS[mtype].model_validate(data) == ex.MESSAGE_EXAMPLES[mtype]  # JSON round-trip


@pytest.mark.parametrize("name", sorted(DOMAIN_MODELS))
def test_domain_examples_match_exported_schema(name: str) -> None:
    data = ex.DOMAIN_EXAMPLES[name].model_dump(mode="json")
    _validate(SCHEMAS[f"domain/{name}.schema.json"], data)
    DOMAIN_MODELS[name].model_validate(data)


def test_schemas_declare_dialect_and_version(tmp_path) -> None:
    paths = export(tmp_path)
    assert len(paths) == 15 + len(DOMAIN_MODELS) + 2
    for p in paths:
        s = json.loads(p.read_text())
        assert s["$schema"].endswith("2020-12/schema") and s["x-schema-version"] == "1.0"


def test_envelope_roundtrip_and_typed_payload() -> None:
    env = make_envelope(ex.MESSAGE_EXAMPLES["task.assign"], sender="manager-1", receiver="research-1a2b3c4d",
                        correlation_id=ex.TASK, task_id=ex.TASK)
    _validate(SCHEMAS["Envelope.schema.json"], env.model_dump(mode="json"))
    parsed, payload = parse_envelope(env.model_dump_json())
    assert parsed.message_id == env.message_id and isinstance(payload, TaskAssign)
    assert parsed.execution_id == ex.EXECUTION  # derived from the payload


def test_unknown_fields_are_ignored_for_forward_compatibility() -> None:
    raw = make_envelope(ex.MESSAGE_EXAMPLES["task.ack"], sender="a", correlation_id="c").model_dump(mode="json")
    raw["future_field"] = 1
    raw["payload"]["future_payload_field"] = "x"
    raw["schema_version"] = "1.7"  # newer minor, same major
    env, payload = parse_envelope(raw)
    assert not hasattr(env, "future_field") and "future_payload_field" not in payload.model_dump()


def test_new_major_version_is_rejected() -> None:
    raw = make_envelope(ex.MESSAGE_EXAMPLES["task.ack"], sender="a", correlation_id="c").model_dump(mode="json")
    raw["schema_version"] = "2.0"
    with pytest.raises(SchemaUnsupported):
        parse_envelope(raw)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(message_type="task.unknown"),
    lambda r: r["payload"].pop("decision"),
    lambda r: r["payload"].update(decision="maybe"),
    lambda r: r.update(traceparent="not-a-traceparent"),
    lambda r: r.pop("sender"),
])
def test_invalid_messages_raise_invalid_message(mutate) -> None:
    raw = make_envelope(ex.MESSAGE_EXAMPLES["task.ack"], sender="a", correlation_id="c").model_dump(mode="json")
    mutate(raw)
    with pytest.raises(InvalidMessage):
        parse_envelope(raw)


def test_commands_need_a_receiver() -> None:
    with pytest.raises(InvalidMessage):
        parse_envelope(make_envelope(ex.MESSAGE_EXAMPLES["task.cancel"], sender="manager-1", receiver="x",
                                     correlation_id="c").model_dump(mode="json") | {"receiver": None})


def test_oversized_message_rejected() -> None:
    with pytest.raises(InvalidMessage):
        parse_envelope(b"{" + b" " * (300 * 1024) + b"}")


def test_version_negotiation() -> None:
    assert negotiate(["1.0", "1.1"], ["1.1", "2.0"]) == "1.1"
    assert negotiate(["1.0"], ["2.0"]) is None
    assert is_compatible("1.9") and not is_compatible("2.0")


def test_task_graph_rejects_cycles_and_unknown_deps() -> None:
    tasks = [t.model_dump() for t in ex.TASK_GRAPH.tasks]
    tasks[0]["depends_on"] = ["T5"]  # T1 -> ... -> T5 -> T1
    with pytest.raises(ValueError, match="cycle"):
        TaskGraph(project_id="P", tasks=tasks)
    with pytest.raises(ValueError, match="unknown"):
        TaskGraph(project_id="P", tasks=[{"id": "A", "title": "a", "agent_capability": "echo", "depends_on": ["Z"]}])
    assert {"from": "T1", "to": "T2"} in ex.TASK_GRAPH.edges


def test_requirement_set_checks_marks_and_ids() -> None:
    data = ex.REQUIREMENT_SET.model_dump()
    data["total_marks"] = 90
    with pytest.raises(ValueError, match="marks"):
        RequirementSet.model_validate(data)
    data = ex.REQUIREMENT_SET.model_dump()
    data["requirements"][1]["id"] = "R1"
    with pytest.raises(ValueError, match="duplicate"):
        RequirementSet.model_validate(data)


def test_research_report_claims_must_cite_known_evidence() -> None:
    data = ex.RESEARCH_REPORT.model_dump()
    data["claims"][0]["evidence_ids"] = ["EV404"]
    with pytest.raises(ValueError, match="unknown evidence"):
        type(ex.RESEARCH_REPORT).model_validate(data)


def test_envelope_is_exported_in_package_api() -> None:
    assert Envelope.model_fields["schema_version"].default == "1.0"
