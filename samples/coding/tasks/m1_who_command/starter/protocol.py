"""Chat line protocol: slash commands."""


def parse_command(line: str) -> tuple[str, list[str]]:
    """Split a chat line into (command, args); plain text is ("say", [text])."""
    line = line.strip()
    if not line.startswith("/"):
        return "say", [line]
    name, _, rest = line[1:].partition(" ")
    if name == "nick":
        return "nick", [rest]
    if name == "msg":
        target, _, text = rest.partition(" ")
        return "msg", [target, text]
    if name == "quit":
        return "quit", []
    raise ValueError(f"unknown command /{name}")
