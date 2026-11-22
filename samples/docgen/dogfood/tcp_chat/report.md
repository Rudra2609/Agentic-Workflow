# Project report

## Overview

The `tcp_chat` repository implements a command-line chat system using a custom line protocol defined in `protocol.py` for handling commands and length-prefixed frames. The system relies on a threaded TCP chat server managed by `server.py`, which handles one thread per connected client, enforces unique nicknames, and manages message broadcasting. Users connect to this server via the command-line interface provided in `client.py`. Additionally, the repository includes a test suite that uses pytest to verify the project's functionality.

## Design

| Component | Modules | What it is |
|---|---|---|
| `client.py` | 1 | Command-line chat client. |
| `protocol.py` | 1 | Line protocol for the chat: commands and length-prefixed frames. |
| `server.py` | 1 | Threaded TCP chat server: one thread per client, unique nicknames, broadcast. |

## Implementation

- `protocol.py`: Line protocol for the chat: commands and length-prefixed frames.
- `client.py`: Command-line chat client.
- `server.py`: Threaded TCP chat server: one thread per client, unique nicknames, broadcast.

## Testing

1 test file(s) with 2 test functions.

```bash
pytest
```

## How to run

```bash
pip install -r requirements.txt
python client.py --nick VALUE
python server.py
```
