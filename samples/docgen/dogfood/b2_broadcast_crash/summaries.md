# Code summaries: b2_broadcast_crash

The b2_broadcast_crash repository implements a simple chat system using a command‑line client (client.py) that connects to a line‑echo server (server.py). Messages are transmitted as length‑prefixed frames defined in framing.py, where each frame consists of a 4‑byte big‑endian length followed by a UTF‑8 body. The protocol for chat lines, including slash commands, is handled by protocol.py, while room.py maintains the set of connected clients identified by nickname. The application has no dependencies, listens on port 5050, and defines no endpoints or environment variables.

Public functions and classes: 13; described: 69 % (from docstrings or the model; the rest show their signature).

## `client.py`

“Command-line chat client.”

- `client.py::main`: Parses command-line arguments, connects to server, sends user input lines until '/quit' is entered.

## `framing.py`

“Length-prefixed frames: 4-byte big-endian length + UTF-8 body.”

- `framing.py::frame`: `def frame(message: str) -> bytes`
- `framing.py::unframe`: “Return the complete messages in buffer and the unused tail.”

## `protocol.py`

“Chat line protocol: slash commands.”

- `protocol.py::parse_command`: “Split a chat line into (command, args); plain text is ("say", [text]).”

## `room.py`

“The chat room: connected clients by nickname.”

- `room.py::Room`: `class Room`
- `room.py::Room.__init__`: `def __init__(self) -> None`
- `room.py::Room.join`: “Add a client; False if the nickname is taken (case-insensitive).”
- `room.py::Room.leave`: `def leave(self, nick: str) -> None`
- `room.py::Room.broadcast`: “Send text to every open connection, drop closed ones; return how many got it.”

## `server.py`

“Line echo server for the chat project.”

- `server.py::EchoServer`: Defines a class that creates a TCP server socket and stores its listening port.
- `server.py::EchoServer.__init__`: Initializes the server by creating a listening socket on the given host and port, storing the assigned port.
- `server.py::EchoServer.handle`: “Reply "echo: <line>" to every line the client sends.”
- `server.py::EchoServer.serve_forever`: Continuously accepts client connections and processes each with the handle method.
