# Chat‑Room Demo  
*A tiny, educational chat server/client written in pure Python.*

---

## Table of Contents
1. [Overview](#overview)  
2. [Features](#features)  
3. [Project Structure](#project-structure)  
4. [Installation](#installation)  
5. [Running the Server](#running-the-server)  
6. [Running the Client](#running-the-client)  
7. [Configuration & Command‑Line Options](#configuration--command-line-options)  
8. [Protocol Details](#protocol-details)  
9. [Testing](#testing)  
10. [Contributing](#contributing)  
11. [License](#license)  

---

## Overview
This repository contains a **minimal chat system** that demonstrates:

* A **TCP echo server** (`server.py`) that replies with `echo: <message>`.
* A **command‑line client** (`client.py`) that connects to the server and streams user input.
* Simple **framing utilities** (`framing.py`) for length‑prefixed messages.
* A **chat‑room abstraction** (`room.py`) that manages nicknames and broadcasting.
* A **command parser** (`protocol.py`) that recognises slash‑commands (`/nick`, `/msg`, `/quit`).

The code is deliberately lightweight and uses only the Python standard library, making it perfect for learning about sockets, threading, and basic protocol design.

---

## Features
| Component | What it does |
|-----------|--------------|
| **EchoServer** | Accepts TCP connections, reads lines, and replies with `echo: …`. |
| **Client** | Reads stdin until `/quit` is typed, sends each line to the server. |
| **Framing** | Provides `frame()` / `unframe()` for length‑prefixed UTF‑8 messages (useful for future extensions). |
| **Room** | Thread‑safe nickname registration, leave handling, and broadcast to all connected clients. |
| **Protocol** | Parses slash commands into a `(command, args)` tuple; unknown commands raise `ValueError`. |
| **Zero‑dependency** | Only the Python standard library is required. |

---

## Project Structure
```
.
├── client.py      # CLI chat client
├── server.py      # Simple line‑echo server
├── framing.py     # Length‑prefixed framing helpers
├── protocol.py    # Slash‑command parser
├── room.py        # Thread‑safe chat‑room manager
├── tests/         # Unit tests (see Testing section)
└── README.md
```

---

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/your‑username/chat-room-demo.git
   cd chat-room-demo
   ```

2. **(Optional) Create a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # on Windows: .venv\Scripts\activate
   ```

3. **Install development dependencies** (only needed for running the test suite)
   ```bash
   pip install -U pip
   pip install -r requirements.txt   # file contains pytest, pytest‑asyncio, etc.
   ```

> **Note:** The core code has **no external dependencies**; the above steps are only for testing.

---

## Running the Server

The server is an **echo server** that listens on `127.0.0.1` and a random free port (or a port you specify).

```bash
python -m server          # uses default host 127.0.0.1 and OS‑chosen port
```

Or specify a custom host/port:

```bash
python -m server --host 0.0.0.0 --port 5050
```

The server prints the actual port it bound to (useful when `port=0`).

**Example output**
```
Listening on 127.0.0.1:5050
```

The server runs forever until you interrupt it (`Ctrl+C`).

---

## Running the Client

```bash
python -m client [--host HOST] [--port PORT]
```

*Default*: `--host 127.0.0.1 --port 5050`

The client reads from **stdin** line‑by‑line. Type `/quit` to close the connection and exit.

```text
> hello world
> /nick Alice
> /msg Bob Hi Bob!
> /quit
```

All lines (including slash commands) are sent verbatim to the server; the server will echo them back prefixed with `echo:`.

---

## Configuration & Command‑Line Options

| Script | Option | Description | Default |
|--------|--------|-------------|---------|
| `client.py` | `--host` | Server hostname or IP address | `127.0.0.1` |
|            | `--port` | Server TCP port | `5050` |
| `server.py` | `--host` | Interface to bind (e.g., `0.0.0.0` for all) | `127.0.0.1` |
|            | `--port` | Port number (`0` = let OS pick) | `0` |

You can also set environment variables (`CHAT_HOST`, `CHAT_PORT`) and modify the scripts to read them if you prefer.

---

## Protocol Details

### Framing (`framing.py`)
- **frame(message: str) → bytes**  
  Returns a 4‑byte big‑endian length prefix followed by the UTF‑8 encoded body.
- **unframe(buffer: bytes) → (list[str], bytes)**  
  Extracts all complete messages from a byte buffer, returning the list of decoded strings and any remaining partial data.

> The current echo server does **not** use framing; it works line‑based. The utilities are provided for future binary‑protocol extensions.

### Slash Commands (`protocol.py`)
```python
parse_command("/nick Alice")   # → ("nick", ["Alice"])
parse_command("/msg Bob Hi")   # → ("msg", ["Bob", "Hi"])
parse_command("/quit")         # → ("quit", [])
parse_command("Just text")     # → ("say", ["Just text"])
```
- Unknown commands raise `ValueError`.
- Plain text is treated as a `say` command.

### Room (`room.py`)
- `join(nick, conn)` – registers a client; returns `False` if the nickname (case‑insensitive) is already taken.
- `leave(nick)` – removes a client.
- `broadcast(text)` – sends `text` to every connected client, cleaning up closed sockets; returns the number of successful deliveries.

> The current server implementation does **not** use `Room`; it is included to illustrate how a full‑featured chat server could be built.

---

## Testing

The repository includes a basic test suite using **pytest**.

### Run all tests
```bash
pytest
```

### Test layout
- `tests/test_framing.py` – verifies `frame`/`unframe` round‑trip.
- `tests/test_protocol.py` – checks command parsing and error handling.
- `tests/test_room.py` – exercises nickname registration, leaving, and broadcasting.
- `tests/test_server_client.py` – integration test that starts an `EchoServer` in a background thread and talks to it with a client socket.

### Adding new tests
Create a file `tests/test_<module>.py` and follow the existing pattern. Use fixtures for temporary sockets or mock objects as needed.

---

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/awesome‑thing`).
3. Write code **and** tests.
4. Ensure all tests pass (`pytest -q`).
5. Open a Pull Request with a clear description of your changes.

Style guidelines:
- Follow PEP 8.
- Use type hints (already present in the code base).
- Keep imports minimal and from the standard library unless a strong case is made.

---

## License

This project is released under the **MIT License** – see the `LICENSE` file for details.