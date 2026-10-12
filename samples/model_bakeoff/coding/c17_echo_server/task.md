Write a class `EchoServer` using only the Python standard library (`socket`, `threading` or `socketserver`).

- `EchoServer(host: str = "127.0.0.1", port: int = 0)`; port 0 means "pick a free port".
- `start() -> int` starts serving in the background (it must return immediately) and returns the actual port.
- For every line a client sends (terminated by `\n`), the server replies with the same line in UPPER CASE, followed by `\n`.
- Several clients must be served at the same time; one idle client must not block the others.
- `stop()` stops the server and releases the port.
