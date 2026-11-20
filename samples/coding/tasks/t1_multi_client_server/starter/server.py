"""Line echo server for the chat project."""

import socket


class EchoServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.sock = socket.create_server((host, port))
        self.port = self.sock.getsockname()[1]

    def handle(self, conn: socket.socket) -> None:
        """Reply "echo: <line>" to every line the client sends."""
        with conn, conn.makefile("r", encoding="utf-8") as lines:
            for line in lines:
                conn.sendall(f"echo: {line.strip()}\n".encode("utf-8"))

    def serve_forever(self) -> None:
        while True:
            conn, _ = self.sock.accept()
            self.handle(conn)
