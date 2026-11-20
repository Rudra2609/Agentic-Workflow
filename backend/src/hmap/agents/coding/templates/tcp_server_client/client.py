"""TCP chat client: lines typed on stdin are sent to the server; messages from the server are printed.

    python client.py --host 127.0.0.1 --port 5000
"""

import argparse
import socket
import sys
import threading

from protocol import LineReader, encode


class ChatClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5000, timeout: float | None = None) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._reader = LineReader()
        self._pending: list[str] = []

    def send(self, message: str) -> None:
        self.sock.sendall(encode(message))

    def receive(self) -> str:
        """The next complete message from the server (blocks; raises ConnectionError when the server closed)."""
        while not self._pending:
            data = self.sock.recv(4096)
            if not data:
                raise ConnectionError("server closed the connection")
            self._pending.extend(self._reader.feed(data))
        return self._pending.pop(0)

    def close(self) -> None:
        self.sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="TCP chat client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    client = ChatClient(args.host, args.port)

    def printer() -> None:
        try:
            while True:
                print(client.receive())
        except (ConnectionError, OSError):
            print("disconnected")

    threading.Thread(target=printer, daemon=True).start()
    for line in sys.stdin:
        client.send(line.rstrip("\n"))
    client.close()


if __name__ == "__main__":
    main()
