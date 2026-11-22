# Code summaries: tcp_chat

The `tcp_chat` repository implements a command-line chat system using a custom line protocol defined in `protocol.py` for handling commands and length-prefixed frames. The system relies on a threaded TCP chat server managed by `server.py`, which handles one thread per connected client, enforces unique nicknames, and manages message broadcasting. Users connect to this server via the command-line interface provided in `client.py`. Additionally, the repository includes a test suite that uses pytest to verify the project's functionality.

Public functions and classes: 13; described: 100 % (from docstrings or the model; the rest show their signature).

## `client.py`

“Command-line chat client.”

- `client.py::receive`: Continuously receives data from a socket, unframes messages, and prints each message.
- `client.py::main`: Parses command-line arguments, connects to a server, sends a nickname, starts a receiver thread, and sends user input until '/quit'.

## `protocol.py`

“Line protocol for the chat: commands and length-prefixed frames.”

- `protocol.py::ProtocolError`: “Raised for a malformed command or frame.”
- `protocol.py::parse_command`: “Split ``/nick alice`` into ("nick", ["alice"]); plain text is ("say", [text]).”
- `protocol.py::frame`: Creates a 4-byte big-endian length prefix followed by the UTF-8 encoded message bytes.
- `protocol.py::unframe`: “Return the complete messages in ``buffer`` and the unused tail.”

## `server.py`

“Threaded TCP chat server: one thread per client, unique nicknames, broadcast.”

- `server.py::Room`: “Connected clients by nickname; every method is thread-safe.”
- `server.py::Room.__init__`: Initializes a thread-safe room with a lock and empty client dictionary.
- `server.py::Room.join`: Adds a client if nickname is unique and room not full, returning success status.
- `server.py::Room.leave`: Removes a client by nickname from the room.
- `server.py::Room.broadcast`: Sends a framed message to all connected clients.
- `server.py::handle_client`: Processes client commands, manages nickname registration, broadcasting, and disconnection.
- `server.py::serve`: Starts the server, accepting connections and spawning a thread per client.
