"""Wire format: UTF-8 text messages, one per line (``\\n``-terminated). Lines longer than MAX_LINE are refused."""

MAX_LINE = 4096
ENCODING = "utf-8"


def encode(message: str) -> bytes:
    """One message as bytes on the wire (newlines inside a message become spaces)."""
    text = message.replace("\r", " ").replace("\n", " ")
    data = (text + "\n").encode(ENCODING)
    if len(data) > MAX_LINE:
        raise ValueError(f"message longer than {MAX_LINE} bytes")
    return data


class LineReader:
    """Splits a byte stream into complete lines; keeps a partial line until the rest arrives."""

    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, data: bytes) -> list[str]:
        self._buffer += data
        lines = []
        while b"\n" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\n", 1)
            lines.append(raw.decode(ENCODING, "replace").rstrip("\r"))
        if len(self._buffer) > MAX_LINE:
            self._buffer = b""
            raise ValueError("line too long")
        return lines
