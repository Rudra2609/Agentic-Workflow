# TCP Chat – Simple Multi‑Client Chat Server & Client  

A tiny, pure‑Python implementation of a line‑based TCP chat system.  
The **server** accepts many simultaneous connections, broadcasting every
message it receives to all other connected clients.  
The **client** reads lines from *stdin*, sends them to the server, and prints
incoming messages to *stdout*.

> **Why this project?**  
> • Demonstrates socket programming, threading and a tiny custom protocol.  
> • Zero external dependencies – just the Python standard library.  
> • Fully unit‑tested and ready to be used as a teaching example or a quick
>   internal chat tool.

---

## Table of Contents  

1. [Features](#features)  
2. [Installation](#installation)  
3. [Running the Server](#running-the-server)  
4. [Running the Client](#running-the-client)  
5. [Configuration & Protocol Details](#configuration--protocol-details)  
6. [API Reference](#api-reference)  
7. [Testing](#testing)  
8. [Troubleshooting & FAQ](#troubleshooting--faq)  
9. [License](#license)  

---

## Features  

- **Multi‑client**: each client runs in its own thread; messages are broadcast
  to all others.  
- **Line‑based protocol**: UTF‑8 text, one message per `\n`‑terminated line.  
- **Automatic client cleanup**: disconnects are detected and removed without
  affecting remaining users.  
- **Configurable host/port** via command‑line arguments (defaults to
  `127.0.0.1:5000`).  
- **Message length limit** (`MAX_LINE = 4096` bytes) to avoid abuse.  
- **Thread‑safe** internal data structures.  
- **Unit tests** covering protocol handling and server behaviour.  

---

## Installation  

The project requires **Python 3.9+** (type‑hints use the `|` union syntax).  
No third‑party packages are needed.

```bash
# Clone the repository
git clone https://github.com/yourname/tcp-chat.git
cd tcp-chat

# (Optional) create a virtual environment
python -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate

# Verify the interpreter version
python --version   # should be >= 3.9
```

All source files are in the repository root:

- `server.py` – chat server  
- `client.py` – chat client  
- `protocol.py` – wire format helpers  
- `test_chat.py` – unit tests  

---

## Running the Server  

```bash
python server.py [--host HOST] [--port PORT]
```

- `--host` – IP address to bind (default `127.0.0.1`).  
- `--port` – Port number (default `5000`). Use `0` to let the OS pick a free
  port; the actual port is printed on start‑up.

**Example**

```bash
$ python server.py --host 0.0.0.0 --port 5000
listening on 0.0.0.0:5000
```

The server runs forever until you press **Ctrl‑C**, at which point it shuts
down gracefully, closing all client sockets.

---

## Running the Client  

```bash
python client.py [--host HOST] [--port PORT]
```

- `--host` – Server address (default `127.0.0.1`).  
- `--port` – Server port (default `5000`).  

After starting, type a line and press **Enter** – the line is sent to the
server. Incoming messages from other participants appear on the console.

**Example**

```bash
$ python client.py --host 127.0.0.1 --port 5000
Hello everyone!          # you type this
client1: Hello everyone! # message echoed back from server
```

To quit, send EOF (`Ctrl‑D` on Unix, `Ctrl‑Z` then `Enter` on Windows) or
terminate the process.

---

## Configuration & Protocol Details  

### Wire format (`protocol.py`)

- **Encoding**: UTF‑8.  
- **Message delimiter**: newline `\n`.  
- **Maximum line size**: `MAX_LINE = 4096` bytes (including the trailing
  newline). Longer messages raise `ValueError`.  
- **Sanitisation**: carriage returns `\r` and newlines inside a message are
  replaced with spaces before transmission.

```python
# Encode a Python string to bytes ready for the wire
data = encode("my message")   # b"my message\n"
```

### Server internals  

- Each accepted socket is stored in a thread‑safe dictionary
  `self._clients: dict[socket.socket, str]`.  
- A unique name (`client1`, `client2`, …) is assigned for display.  
- `broadcast(message, sender=None)` sends a line to every client **except**
  the sender. Failed sends cause the offending client to be removed.  

### Client internals  

- `ChatClient.send(message)` – encodes and transmits a line.  
- `ChatClient.receive()` – blocks until a full line is received, raising
  `ConnectionError` if the server disconnects.  

---

## API Reference  

### `protocol.encode(message: str) -> bytes`  

Converts a string to the wire format, replacing internal newlines and
ensuring the length limit.

### `protocol.LineReader`  

Utility class for incremental parsing of a byte stream.

| Method | Description |
|--------|-------------|
| `feed(data: bytes) -> list[str]` | Append raw bytes, return any complete lines that were formed. Raises `ValueError` if a line exceeds `MAX_LINE`. |

### `client.ChatClient(host: str = "127.0.0.1", port: int = 5000, timeout: float | None = None)`  

| Method | Description |
|--------|-------------|
| `send(message: str) -> None` | Send a line to the server. |
| `receive() -> str` | Block until the next complete line arrives. |
| `close() -> None` | Close the underlying socket. |

### `server.ChatServer(host: str = "127.0.0.1", port: int = 0)`  

| Method | Description |
|--------|-------------|
| `start() -> int` | Bind, listen and start accepting clients on a background thread. Returns the actual listening port. |
| `stop() -> None` | Stop accepting new connections and close all existing ones. |
| `client_count() -> int` | Return the current number of connected clients. |
| `broadcast(message: str, sender: socket.socket | None = None) -> None` | Send a message to all clients except `sender`. |
| `._name(conn) -> str` *(internal)* | Retrieve the human‑readable name for a connection. |

---

## Testing  

The test suite uses the standard library `unittest`. It validates both the
protocol helpers and the server’s multi‑client behaviour.

```bash
# Run all tests
python -m unittest test_chat.py
```

You should see something like:

```
...
----------------------------------------------------------------------
Ran 3 tests in 0.XXXs

OK
```

The tests spin up a real `ChatServer` on an OS‑assigned port (`port=0`) and
connect several `ChatClient` instances to verify:

- Proper line parsing and handling of partial data.  
- Broadcast reaches every other client.  
- Clients can operate concurrently.  
- Disconnecting one client does not affect the others.  

---

## Troubleshooting & FAQ  

**Q: “Connection refused” when starting the client.**  
A: Ensure the server is running and listening on the same host/port. Use
`netstat -tlnp` (Linux/macOS) or `Get-NetTCPConnection` (PowerShell) to verify.

**Q: Messages are truncated or not delivered.**  
A: The protocol limits each line to 4096 bytes. Longer inputs raise an error
on the sending side; split them manually.

**Q: I see “line too long” errors on the server.**  
A: A client sent a line exceeding the limit, or a malicious client is spamming.
The server discards the offending connection.

**Q: Can I run the server on a public interface?**  
A: Yes – set `--host 0.0.0.0`. Be aware that the protocol has no authentication
or encryption; use it only on trusted networks or wrap it with TLS/SSH tunnels.

**Q: How do I add authentication or TLS?**  
A: The code is deliberately minimal. You can subclass `ChatServer` and replace
the raw sockets with `ssl.wrap_socket` or implement a simple handshake before
entering the main loop.

---

## License  

This project is released under the **MIT License** – feel free to use,
modify, and distribute it as you wish. See the `LICENSE` file for the full
text.