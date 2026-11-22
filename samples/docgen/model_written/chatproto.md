# chatproto  

A tiny, well‑tested chat protocol implementation written in pure Python.  
It provides:

* **Command parsing** – `/nick`, `/msg`, `/quit` and plain‑text messages.  
* **Unique nickname registry** – case‑insensitive, thread‑safe handling of client nicknames.  
* **Length‑prefixed framing** – robust handling of TCP stream fragmentation and concatenation.  

The module (`chatproto.py`) is the **known‑good** reference implementation used for teaching TCP‑chat assignments. A set of deliberately broken variants lives in `../variants/`; the supplied test suite (`test_chatproto.py`) verifies that the reference passes all tests while each variant fails in its intended way.

---

## Table of Contents  

1. [Features](#features)  
2. [Installation](#installation)  
3. [Quick Start](#quick-start)  
4. [API Reference](#api-reference)  
5. [Configuration](#configuration)  
6. [Running the Tests](#running-the-tests)  
7. [Contributing](#contributing)  
8. [License](#license)  

---

## Features  

| Feature | Description |
|---------|-------------|
| **Command parsing** | `parse_command(line: str) -> (cmd, args)` parses user input, handling case‑insensitivity and validation. |
| **Nickname registry** | `NicknameRegistry` guarantees unique nicknames across threads, validates length (1‑16) and alphanumeric characters. |
| **Message framing** | `frame(message: str) -> bytes` creates a 4‑byte big‑endian length prefix + UTF‑8 payload. |
| **Message unframing** | `unframe(buffer: bytes) -> (messages, remainder)` extracts all complete messages from a byte buffer, leaving any partial frame for later. |
| **Thread‑safety** | Registry uses a `threading.Lock`; framing/unframing are pure functions. |
| **Comprehensive tests** | `pytest` suite covering normal operation and edge cases. |

---

## Installation  

The library has **no external dependencies** beyond the Python standard library.

```bash
# Clone the repository
git clone https://github.com/yourusername/chatproto.git
cd chatproto

# (Optional) Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate

# Install the package in editable mode (useful for development)
pip install -e .
```

> **Note**: The package is pure Python, so it works with any CPython version ≥ 3.8.

---

## Quick Start  

```python
from chatproto import (
    parse_command,
    NicknameRegistry,
    frame,
    unframe,
    ProtocolError,
)

# 1️⃣ Parse a line from a client
cmd, args = parse_command("/nick Ada")   # -> ('nick', ['Ada'])

# 2️⃣ Register a nickname (thread‑safe)
registry = NicknameRegistry()
if not registry.register("client-1", "Ada"):
    raise ValueError("Nickname already taken")

# 3️⃣ Frame a message for sending over TCP
payload = frame("Hello, world!")   # b'\x00\x00\x00\x0cHello, world!'

# 4️⃣ On the receiving side, accumulate bytes and unframe
incoming = b''                     # buffer that grows as you recv()
incoming += payload                # simulate receiving the whole frame
messages, incoming = unframe(incoming)
print(messages)                    # ['Hello, world!']
```

Integrate these building blocks into your own TCP server/client loops; the protocol guarantees that messages are correctly delimited even when TCP splits or merges frames.

---

## API Reference  

### `parse_command(line: str) -> tuple[str, list[str]]`  

* **Purpose** – Convert a raw line from a client into a structured command.  
* **Supported commands**  
  * `/nick <nick>` → `('nick', [nick])`  
  * `/msg <target> <text>` → `('msg', [target, text])`  
  * `/quit` → `('quit', [])`  
  * Anything not starting with `/` → `('say', [text])`  
* **Raises** `ProtocolError` for malformed commands or unknown verbs.  

### `class NicknameRegistry`  

* **Methods**  
  * `register(client_id: str, nick: str) -> bool` – Returns `True` if registration succeeded; `False` if the nickname is already taken. Raises `ProtocolError` for invalid nicknames.  
  * `unregister(nick: str) -> None` – Removes a nickname from the registry (case‑insensitive).  
  * `__len__() -> int` – Number of currently registered nicknames.  

* **Thread‑safety** – All public methods acquire an internal `threading.Lock`.  

### `frame(message: str) -> bytes`  

* Prefixes the UTF‑8 encoded message with a 4‑byte big‑endian length field.  

### `unframe(buffer: bytes) -> tuple[list[str], bytes]`  

* Extracts **all** complete messages from `buffer`.  
* Returns a tuple: `(list_of_messages, remaining_bytes)`.  
* Handles arbitrary TCP fragmentation; incomplete frames are left untouched for the next read.  

### `class ProtocolError(ValueError)`  

* Raised for any protocol‑level violation (invalid command, bad nickname, etc.).  

---

## Configuration  

The module is deliberately **configuration‑free** – all limits are hard‑coded to keep the implementation minimal and pedagogical:

| Constant | Meaning |
|----------|---------|
| `MAX_NICK = 16` | Maximum nickname length (characters). |
| Nickname validation | Must be 1‑16 alphanumeric characters (`str.isalnum()`). |

If you need to adjust these limits, fork the repository and modify the constants accordingly.

---

## Running the Tests  

The test suite uses **pytest**. It validates the reference implementation and ensures that each broken variant fails in its expected way.

```bash
# Install test dependencies
pip install pytest

# Run the tests
pytest -q
```

You should see **all tests passing** for `chatproto.py`. To verify a broken variant, replace the import line in `test_chatproto.py` with the path to the variant and re‑run; the suite will report the intended failures.

---

## Contributing  

Contributions are welcome! Typical ways to help:

* **Bug reports / feature requests** – Open an issue with a clear description.  
* **Pull requests** – Fork the repo, make your changes, and submit a PR. Please keep the following in mind:  
  * Preserve the existing API (function signatures, exception types).  
  * Add or update tests to cover new behavior.  
  * Run the full test suite (`pytest`) before submitting.  

---

## License  

This project is released under the **MIT License** – see the `LICENSE` file for details.  

---  

*Happy chatting!*