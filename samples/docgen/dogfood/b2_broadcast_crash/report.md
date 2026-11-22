# Project report

## Overview

The b2_broadcast_crash repository implements a simple chat system using a command‑line client (client.py) that connects to a line‑echo server (server.py). Messages are transmitted as length‑prefixed frames defined in framing.py, where each frame consists of a 4‑byte big‑endian length followed by a UTF‑8 body. The protocol for chat lines, including slash commands, is handled by protocol.py, while room.py maintains the set of connected clients identified by nickname. The client uses path::client.main to read user input, path::server.handle_connection to echo lines, and path::framing.encode_frame to package messages for transmission.

## Design

| Component | Modules | What it is |
|---|---|---|
| `client.py` | 1 | Command-line chat client. |
| `framing.py` | 1 | Length-prefixed frames: 4-byte big-endian length + UTF-8 body. |
| `protocol.py` | 1 | Chat line protocol: slash commands. |
| `room.py` | 1 | The chat room: connected clients by nickname. |
| `server.py` | 1 | Line echo server for the chat project. |

## Implementation

- `client.py`: Command-line chat client.
- `framing.py`: Length-prefixed frames: 4-byte big-endian length + UTF-8 body.
- `protocol.py`: Chat line protocol: slash commands.
- `room.py`: The chat room: connected clients by nickname.
- `server.py`: Line echo server for the chat project.

## Testing

The code has no test files.

## How to run

```bash
python client.py
```
