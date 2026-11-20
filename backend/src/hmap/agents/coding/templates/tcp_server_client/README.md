# TCP chat (server + client)

```bash
python server.py --port 5000          # terminal 1
python client.py --port 5000          # terminals 2, 3, …: type a line, every other client sees it
python -m unittest                    # tests: broadcast, concurrent clients, disconnects
```

- `protocol.py`: newline-framed UTF-8 messages (`encode`, `LineReader`).
- `server.py`: `ChatServer` serves every client on its own thread and broadcasts each message to the others.
- `client.py`: `ChatClient` (`send`, `receive`) and an interactive `main`.
