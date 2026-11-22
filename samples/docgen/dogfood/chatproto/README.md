# chatproto

chatproto is a tiny chat protocol implementation written in Python. It provides the core logic for handling commands, enforcing unique nicknames, and framing messages in a TCP‑chat style application. The library is suitable for developers who need a simple, standard‑library‑only solution for building chat‑related functionality.

## Architecture

```mermaid
flowchart LR
  chatproto["chatproto.py"]
```

More: [architecture](architecture.md).

## Code

- `chatproto.py`: “A tiny chat protocol (the kind of code the TCP-chat assignment asks for): commands, unique nicknames, message framing.”

## Tests

```bash
pytest
```
1 test file(s) with 8 test functions: `test_chatproto.py`.
