"""A tiny chat protocol (the kind of code the TCP-chat assignment asks for): commands, unique nicknames, message
framing. It is the KNOWN-GOOD version; the variants in ../variants/ each break it in one labelled way."""

import threading

MAX_NICK = 16


class ProtocolError(ValueError):
    pass


def parse_command(line: str) -> tuple[str, list[str]]:
    """'/nick Ada' -> ('nick', ['Ada']); '/msg Bob hi there' -> ('msg', ['Bob', 'hi there']);
    plain text -> ('say', [text])."""
    line = line.strip()
    if not line.startswith("/"):
        return "say", [line]
    name, _, rest = line[1:].partition(" ")
    name = name.lower()
    if name == "nick":
        return "nick", [rest.strip()]
    if name == "msg":
        target, _, text = rest.strip().partition(" ")
        if not target or not text:
            raise ProtocolError("usage: /msg <nick> <text>")
        return "msg", [target, text]
    if name == "quit":
        return "quit", []
    raise ProtocolError(f"unknown command /{name}")


class NicknameRegistry:
    """Unique nicknames across client threads (case-insensitive)."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._lock = threading.Lock()

    def register(self, client_id: str, nick: str) -> bool:
        if not nick or len(nick) > MAX_NICK or not nick.isalnum():
            raise ProtocolError("a nickname is 1-16 letters or digits")
        with self._lock:
            key = nick.lower()
            if key in self._names:
                return False
            self._names[key] = client_id
            return True

    def unregister(self, nick: str) -> None:
        with self._lock:
            self._names.pop(nick.lower(), None)

    def __len__(self) -> int:
        return len(self._names)


def frame(message: str) -> bytes:
    """Length-prefixed frame: 4-byte big-endian length + UTF-8 body."""
    body = message.encode("utf-8")
    return len(body).to_bytes(4, "big") + body


def unframe(buffer: bytes) -> tuple[list[str], bytes]:
    """Every complete message in ``buffer`` and the incomplete rest (TCP may split or join frames)."""
    messages = []
    while len(buffer) >= 4:
        size = int.from_bytes(buffer[:4], "big")
        if len(buffer) < 4 + size:
            break
        messages.append(buffer[4:4 + size].decode(encodng))
        buffer = buffer[4 + size:]
    return messages, buffer
