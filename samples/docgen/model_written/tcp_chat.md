# Chatty – Simple TCP Chat Server & Client  

A tiny, **thread‑per‑client** chat system written in pure Python.  
It demonstrates a custom length‑prefixed line protocol, basic socket programming, and a clean, test‑driven design.

---

## Table of Contents  

- [Features](#features)  
- [Project Structure](#project-structure)  
- [Installation](#installation)  
- [Running the Server](#running-the-server)  
- [Running the Client](#running-the-client)  
- [Protocol Overview](#protocol-overview)  
- [Configuration](#configuration)  
- [Testing](#testing)  
- [Contributing](#contributing)  
- [License](#license)  

---

## Features  

- **Zero external dependencies** (only the standard library).  
- Length‑prefixed frames → reliable message boundaries over TCP.  
- Simple command set: `/nick`, `/msg`, `/who`, `/quit`.  
- Unique nicknames enforced server‑side.  
- Broadcast of public messages to all connected users.  
- Thread‑safe `Room` implementation using a `Lock`.  
- Fully typed (PEP‑484) and documented code.  
- Pytest test suite covering the protocol utilities.

---

## Project Structure  

```
chatty/
├─ client.py          # CLI chat client
├─ server.py          # Threaded TCP chat server
├─ protocol.py        # Frame/unframe + command parsing
├─ requirements.txt   # Test dependencies
└─ tests/
   └─ test_protocol.py
```

---

## Installation  

1. **Clone the repository**

```bash
git clone https://github.com/yourname/chatty.git
cd chatty
```

2. **Create a virtual environment (optional but recommended)**

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

3. **Install test dependencies**

```bash
pip install -r requirements.txt
```

> The runtime itself needs no third‑party packages.

---

## Running the Server  

The server listens on all interfaces (`0.0.0.0`) and defaults to port **5050**.

```bash
python server.py
```

### Environment variables  

| Variable          | Description                         | Default |
|-------------------|-------------------------------------|---------|
| `CHAT_PORT`       | TCP port the server binds to         | `5050`  |
| `CHAT_MAX_CLIENTS`| Maximum simultaneous connections    | `32`    |

Example with custom settings:

```bash
CHAT_PORT=6000 CHAT_MAX_CLIENTS=100 python server.py
```

The server runs forever, spawning a daemon thread for each new client.

---

## Running the Client  

```bash
python client.py --nick YOUR_NICKNAME [--host HOST] [--port PORT]
```

- `--nick` **(required)** – your desired nickname (max 16 characters, enforced by the server).  
- `--host` – server address, defaults to `127.0.0.1`.  
- `--port` – server port, defaults to `5050`.

**Example**

```bash
python client.py --nick alice
```

After connecting, type messages and press **Enter** to send.  
Enter `/quit` to disconnect gracefully.

---

## Protocol Overview  

All communication uses a **length‑prefixed frame**:

```
[4‑byte big‑endian length][UTF‑8 encoded payload]
```

### Commands (client → server)

| Command | Syntax | Description |
|---------|--------|-------------|
| `/nick` | `/nick <nickname>` | Register a unique nickname. |
| `/msg`  | `/msg <target> <text>` | Private message (not yet implemented on server – placeholder). |
| `/who`  | `/who` | Request list of users (future extension). |
| `/quit` | `/quit` | Close the connection. |
| *plain text* | `Hello world` | Sent as a public message (`say`). |

### Server → client messages  

- `"<nick>: <text>"` – broadcast public chat.  
- `error: <description>` – protocol error (e.g., unknown command, nickname taken).  

The helper functions in **`protocol.py`**:

```python
frame(message: str) -> bytes          # Encode a string into a frame
unframe(buffer: bytes) -> (list, bytes)  # Decode all complete frames from a buffer
parse_command(line: str) -> (str, list) # Turn raw line into (command, args)
```

---

## Configuration  

The only runtime configuration is via environment variables (see *Running the Server*).  
Client options are supplied through command‑line arguments.

If you need to change the maximum nickname length, edit `MAX_NICK` in `protocol.py` and re‑run the server.

---

## Testing  

The project includes a minimal test suite for the protocol utilities.

```bash
pytest -q
```

Expected output:

```
..                                                                    [100%]
2 passed in 0.02s
```

Add more tests under `tests/` as you extend functionality.

---

## Contributing  

Contributions are welcome!  

1. Fork the repository.  
2. Create a feature branch (`git checkout -b feat/awesome-feature`).  
3. Write code **and** accompanying tests.  
4. Ensure all tests pass (`pytest`).  
5. Open a Pull Request with a clear description.

Please follow PEP‑8 style guidelines and keep the code type‑annotated.

---

## License  

This project is released under the **MIT License** – see the `LICENSE` file for details.