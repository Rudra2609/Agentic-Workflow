"""Topic events: pattern matching, fan-out copies, durable vs temporary subscribers, event retry/DLQ."""

import pytest

from hmap.core.bus.base import DLQ_NAME, Bus, Delivery
from hmap.core.bus.topics import topic_matches, validate_pattern
from hmap.core.contracts import DomainEvent
from tests.core.bus._helpers import event, settle, wait_until


@pytest.mark.parametrize(("pattern", "key", "expected"), [
    ("task.*", "task.completed", True),
    ("task.*", "task", False),
    ("task.*", "task.a.b", False),
    ("task.*", "agent.registered", False),
    ("*.completed", "task.completed", True),
    ("*.completed", "research.completed", True),
    ("*.completed", "task.completed.x", False),
    ("#", "task.completed", True),
    ("#", "a.b.c.d", True),
    ("task.#", "task", True),
    ("task.#", "task.a.b", True),
    ("task.#", "agent.a", False),
    ("#.completed", "completed", True),
    ("#.completed", "a.b.completed", True),
    ("a.#.z", "a.z", True),
    ("a.#.z", "a.b.c.z", True),
    ("a.#.z", "a.b.c", False),
    ("*.*", "task.completed", True),
    ("task.completed", "task.completed", True),
    ("task.completed", "task.failed", False),
])
def test_topic_matches(pattern: str, key: str, expected: bool) -> None:
    assert topic_matches(pattern, key) is expected


@pytest.mark.parametrize("bad", ["", "task..x", ".task", "task."])
def test_invalid_patterns(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_pattern(bad)


async def test_topic_routing_to_matching_subscribers(bus: Bus) -> None:
    got: dict[str, list[str]] = {"task.*": [], "#": [], "*.completed": [], "agent.*": []}

    for pattern in got:
        async def handler(d: Delivery, p: str = pattern) -> None:
            assert isinstance(d.body, DomainEvent)
            got[p].append(d.body.event_type)
            await d.ack()
        await bus.subscribe_events(pattern, handler)

    keys = ["task.completed", "task.started", "research.completed", "project.requirements_ready"]
    for k in keys:
        await bus.publish_event(event(k))
    await wait_until(lambda: len(got["#"]) == 4)
    await settle()
    assert got["task.*"] == ["task.completed", "task.started"]
    assert got["#"] == keys
    assert got["*.completed"] == ["task.completed", "research.completed"]
    assert got["agent.*"] == []                               # non-matching subscriber gets nothing


async def test_each_subscriber_gets_its_own_copy(bus: Bus) -> None:
    # keyed by subscriber: the two queues are independent, so delivery order between them is not defined
    bodies: dict[str, DomainEvent] = {}

    async def mutating(d: Delivery) -> None:
        assert isinstance(d.body, DomainEvent)
        d.body.data["n"] = 999                                # must not leak into other subscribers' copies
        bodies["mutating"] = d.body
        await d.ack()

    async def reading(d: Delivery) -> None:
        assert isinstance(d.body, DomainEvent)
        bodies["reading"] = d.body
        await d.ack()

    await bus.subscribe_events("task.*", mutating)
    await bus.subscribe_events("task.*", reading)
    sent = event("task.completed")
    await bus.publish_event(sent)
    await wait_until(lambda: len(bodies) == 2)
    await settle()                                            # let the mutation happen whatever the order
    assert bodies["mutating"] is not bodies["reading"]
    assert sent.data["n"] == 1 and bodies["reading"].data["n"] == 1 and bodies["mutating"].data["n"] == 999
    assert bodies["mutating"].event_id == bodies["reading"].event_id == sent.event_id


async def test_one_copy_per_queue_even_if_several_bindings_match(bus: Bus) -> None:
    got: list[str] = []

    async def handler(d: Delivery) -> None:
        assert isinstance(d.body, DomainEvent)
        got.append(d.body.event_type)
        await d.ack()

    await bus.subscribe_events("task.*", handler, queue="ui-feed")
    await bus.subscribe_events("#", handler, queue="ui-feed")         # second binding + competing consumer
    await bus.publish_event(event("task.completed"))
    await bus.publish_event(event("agent.registered"))
    await wait_until(lambda: len(got) == 2)
    await settle()
    assert sorted(got) == ["agent.registered", "task.completed"]


async def test_durable_subscriber_buffers_while_disconnected(bus: Bus) -> None:
    got: list[str] = []

    async def handler(d: Delivery) -> None:
        assert isinstance(d.body, DomainEvent)
        got.append(d.body.aggregate_id)
        await d.ack()

    sub = await bus.subscribe_events("task.#", handler, queue="audit")
    await bus.publish_event(event("task.completed", "T-1"))
    await wait_until(lambda: got == ["T-1"])
    await sub.cancel()
    await bus.publish_event(event("task.failed", "T-2"))
    await bus.publish_event(event("task.completed", "T-3"))
    await bus.publish_event(event("agent.registered", "A-1"))       # not bound: not buffered
    assert (await bus.queue_depths())["audit"] == 2
    await bus.subscribe_events("task.#", handler, queue="audit")
    await wait_until(lambda: len(got) == 3)
    assert got == ["T-1", "T-2", "T-3"]


async def test_temporary_subscriber_does_not_buffer(bus: Bus) -> None:
    got: list[str] = []

    async def handler(d: Delivery) -> None:
        assert isinstance(d.body, DomainEvent)
        got.append(d.body.aggregate_id)
        await d.ack()

    before = set(await bus.queue_depths())
    sub = await bus.subscribe_events("task.*", handler)
    await bus.publish_event(event("task.completed", "T-1"))
    await wait_until(lambda: got == ["T-1"])
    await sub.cancel()
    await bus.publish_event(event("task.completed", "T-2"))       # nobody listening: dropped
    assert set(await bus.queue_depths()) == before                # the temporary queue is gone
    await bus.subscribe_events("task.*", handler)
    await settle()
    assert got == ["T-1"]


async def test_event_with_no_subscriber_is_dropped(bus: Bus) -> None:
    before = await bus.queue_depths()
    await bus.publish_event(event("task.completed"))
    assert await bus.queue_depths() == before


async def test_event_retry_and_dlq(bus: Bus) -> None:
    calls: list[int] = []

    async def handler(d: Delivery) -> None:
        calls.append(d.attempt)
        if d.attempt == 1:
            await d.nack(requeue=True)
        else:
            await d.reject("cannot project this event")

    await bus.subscribe_events("task.*", handler, queue="projector")
    sent = event("task.completed")
    await bus.publish_event(sent)
    await wait_until(lambda: len(calls) == 2)
    await settle()
    [dl] = await bus.dead_letters()
    assert calls == [1, 2] and dl.queue == "projector" and dl.attempts == 2
    assert dl.body["event_id"] == sent.event_id
    assert (await bus.queue_depths())[DLQ_NAME] == 1
