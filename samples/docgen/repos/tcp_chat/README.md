# TCP chat

A multi-client chat server over plain TCP sockets. The server starts one thread per client, keeps nicknames unique
(case-insensitive) and broadcasts every message to the room. No database and no external services: only the Python
standard library.

## Run
```bash
python server.py
python client.py --nick alice --host 127.0.0.1 --port 5050
```

The server listens on port 5050. Set `CHAT_PORT` to change it and `CHAT_MAX_CLIENTS` to change the room size (32).

## Protocol
Every message is a frame: a 4-byte length followed by UTF-8 text (`frame()` and `unframe()` in `protocol.py`).
Commands start with a slash: `/nick`, `/msg`, `/who`, `/quit`; anything else is said to the room. `parse_command()`
raises `ProtocolError` for an unknown command.

## Design
`server.py` holds the `Room` (a dictionary of clients behind a `threading.Lock`) and `handle_client()`; `client.py`
reads from the socket in a background thread.

## Tests
```bash
pip install -r requirements.txt
pytest
```
The tests in `tests/test_protocol.py` cover framing and command parsing.
