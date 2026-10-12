"""AMQP topic-pattern matching (RabbitMQ topic-exchange semantics), shared by the in-memory bus and by anything
that filters events in-process (e.g. a WebSocket feed).

Routing keys and patterns are dot-separated words. In a pattern ``*`` matches exactly one word and ``#`` matches
zero or more words: ``task.*`` matches ``task.completed`` but not ``task`` or ``task.a.b``; ``#`` matches
everything; ``*.completed`` matches ``task.completed``; ``task.#`` matches ``task`` and ``task.a.b``.
"""

from functools import lru_cache


def validate_pattern(pattern: str) -> None:
    """Raise ``ValueError`` for an empty pattern or one with empty words (``a..b``)."""
    if not pattern or any(word == "" for word in pattern.split(".")):
        raise ValueError(f"invalid topic pattern {pattern!r}")


def topic_matches(pattern: str, routing_key: str) -> bool:
    """True if ``routing_key`` matches the topic ``pattern``."""
    return _match(tuple(pattern.split(".")), tuple(routing_key.split(".")))


@lru_cache(maxsize=4096)
def _match(pattern: tuple[str, ...], key: tuple[str, ...]) -> bool:
    if not pattern:
        return not key
    head, rest = pattern[0], pattern[1:]
    if head == "#":
        # '#' swallows zero words, or one word and stays active
        return _match(rest, key) or (bool(key) and _match(pattern, key[1:]))
    if not key:
        return False
    return (head == "*" or head == key[0]) and _match(rest, key[1:])
