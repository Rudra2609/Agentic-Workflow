"""Identifier helpers.

Message and event ids are UUIDv4 (deduplication keys, research §7). Domain ids are prefixed, time-ordered
ULIDs so they sort by creation time and are readable in logs: ``T-01J9...`` (task), ``E-...`` (execution).
"""

import os
import time
import uuid

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_ulid() -> str:
    """26-character Crockford base32 ULID: 48-bit millisecond timestamp + 80 random bits."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def _prefixed(prefix: str) -> str:
    return f"{prefix}-{new_ulid()}"


def new_project_id() -> str:
    return _prefixed("P")


def new_task_id() -> str:
    return _prefixed("T")


def new_execution_id() -> str:
    return _prefixed("E")


def new_artifact_id() -> str:
    return _prefixed("ART")


def new_context_id() -> str:
    return _prefixed("CTX")


def new_agent_instance_id(agent_name: str) -> str:
    return f"{agent_name}-{new_ulid()[-8:].lower()}"
