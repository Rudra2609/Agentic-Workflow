"""Multi-client TCP chat server: every client is served on its own thread at the same time, and each message a
client sends is broadcast to every other connected client. A client that disconnects is removed without
affecting the others.

    python server.py --host 127.0.0.1 --port 5000
"""

import argparse
import contextlib
import socket
import threading

from protocol import LineReader, encode


class ChatServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._clients: dict[socket.socket, str] = {}
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._next_id = 1

    # --- lifecycle -----------------------------------------------------------------------------------------------
    def start(self) -> int:
        """Bind, listen and accept clients on a background thread; returns the port (useful with port=0)."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen()
        self.port = self._sock.getsockname()[1]
        self._running.set()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def stop(self) -> None:
        self._running.clear()
        if self._sock is not None:
            self._sock.close()
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for conn in clients:
            conn.close()

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    # --- serving -------------------------------------------------------------------------------------------------
    def _accept_loop(self) -> None:
        assert self._sock is not None
        while self._running.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            with self._lock:
                name = f"client{self._next_id}"
                self._next_id += 1
                self._clients[conn] = name
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        reader = LineReader()
        try:
            while self._running.is_set():
                data = conn.recv(4096)
                if not data:
                    break
                for line in reader.feed(data):
                    if line.strip():
                        self.broadcast(f"{self._name(conn)}: {line}", sender=conn)
        except (OSError, ValueError):
            pass
        finally:
            self._remove(conn)

    def broadcast(self, message: str, sender: socket.socket | None = None) -> None:
        """Send ``message`` to every client except ``sender``; clients that fail are dropped."""
        data = encode(message)
        with self._lock:
            targets = [c for c in self._clients if c is not sender]
        for conn in targets:
            try:
                conn.sendall(data)
            except OSError:
                self._remove(conn)

    def _name(self, conn: socket.socket) -> str:
        with self._lock:
            return self._clients.get(conn, "unknown")

    def _remove(self, conn: socket.socket) -> None:
        with self._lock:
            self._clients.pop(conn, None)
        with contextlib.suppress(OSError):
            conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="multi-client TCP chat server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    server = ChatServer(args.host, args.port)
    print(f"listening on {args.host}:{server.start()}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
