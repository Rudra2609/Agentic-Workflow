# Code summaries: chatproto

The repository provides a tiny chat protocol implementation in the single module `chatproto.py`. It defines commands, ensures unique nicknames, and handles message framing for a TCP‑chat style application. The core functionality is implemented in functions such as `chatproto.py::parse_command` and format_message, which work together to process incoming data and construct outgoing messages. The accompanying test file validates these behaviors, confirming that the protocol correctly enforces nickname uniqueness and message structure.

Public functions and classes: 8; described: 100 % (from docstrings or the model; the rest show their signature).

## `chatproto.py`

“A tiny chat protocol (the kind of code the TCP-chat assignment asks for): commands, unique nicknames, message framing.”

- `chatproto.py::ProtocolError`: Defines a custom exception subclassing ValueError for protocol errors.
- `chatproto.py::parse_command`: “'/nick Ada' -> ('nick', ['Ada']); '/msg Bob hi there' -> ('msg', ['Bob', 'hi there']); plain text -> ('say', [text]).”
- `chatproto.py::NicknameRegistry`: “Unique nicknames across client threads (case-insensitive).”
- `chatproto.py::NicknameRegistry.__init__`: Initializes an empty nickname registry with a thread lock.
- `chatproto.py::NicknameRegistry.register`: Registers a unique, alphanumeric nickname for a client, returning False if already taken.
- `chatproto.py::NicknameRegistry.unregister`: Removes a nickname from the registry, ignoring if it does not exist.
- `chatproto.py::frame`: “Length-prefixed frame: 4-byte big-endian length + UTF-8 body.”
- `chatproto.py::unframe`: “Every complete message in ``buffer`` and the incomplete rest (TCP may split or join frames).”
