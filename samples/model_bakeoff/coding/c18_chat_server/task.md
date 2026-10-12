Write a multi-client TCP chat server class `ChatServer` using only the Python standard library.

- `ChatServer(host: str = "127.0.0.1", port: int = 0)`; `start() -> int` serves in the background and returns the port;
  `stop()` shuts everything down.
- All messages are UTF-8 lines terminated by `\n`.
- A client's first line must be `NAME <username>`. If the name is free, reply `OK\n`; if it is already taken by a
  connected client, reply `ERROR name taken\n` and close that connection.
- When a client registers, every *other* registered client receives `* <username> joined\n`.
- Every later line `<text>` from a registered client is sent to every *other* registered client as `<username>: <text>\n`
  (the sender does not receive its own message).
- When a registered client disconnects, every other registered client receives `* <username> left\n`, and the name becomes free again.
