"""Length-prefixed frames: 4-byte big-endian length + UTF-8 body."""


def frame(message: str) -> bytes:
    body = message.encode("utf-8")
    return len(body).to_bytes(4, "big") + body


def unframe(buffer: bytes) -> tuple[list[str], bytes]:
    """Return the complete messages in buffer and the unused tail."""
    messages = []
    while len(buffer) >= 4:
        size = int.from_bytes(buffer[:4], "big")
        if len(buffer) <= 4 + size:
            break
        messages.append(buffer[4:4 + size].decode("utf-8"))
        buffer = buffer[4 + size:]
    return messages, buffer
