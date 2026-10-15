"""Line protocol for the chat: commands and length-prefixed frames."""

MAX_NICK = 16


class ProtocolError(Exception):
    """Raised for a malformed command or frame."""


def parse_command(line: str) -> tuple[str, list[str]]:
    """Split ``/nick alice`` into ("nick", ["alice"]); plain text is ("say", [text])."""
    line = line.strip()
    if not line.startswith("/"):
        return "say", [line]
    name, _, rest = line[1:].partition(" ")
    if name not in ("nick", "msg", "quit", "who"):
        raise ProtocolError(f"unknown command /{name}")
    if name == "msg":
        target, _, text = rest.partition(" ")
        return "msg", [target, text]
    return name, [rest] if rest else []


def frame(message: str) -> bytes:
    body = message.encode("utf-8")
    return len(body).to_bytes(4, "big") + body


def unframe(buffer: bytes) -> tuple[list[str], bytes]:
    """Return the complete messages in ``buffer`` and the unused tail."""
    messages = []
    while len(buffer) >= 4:
        size = int.from_bytes(buffer[:4], "big")
        if len(buffer) < 4 + size:
            break
        messages.append(buffer[4:4 + size].decode("utf-8"))
        buffer = buffer[4 + size:]
    return messages, buffer
