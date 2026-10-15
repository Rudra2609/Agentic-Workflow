"""Threaded TCP chat server: one thread per client, unique nicknames, broadcast."""

import os
import socket
import threading

from protocol import ProtocolError, frame, parse_command, unframe

HOST = "0.0.0.0"
PORT = int(os.environ.get("CHAT_PORT", "5050"))
MAX_CLIENTS = int(os.environ.get("CHAT_MAX_CLIENTS", "32"))


class Room:
    """Connected clients by nickname; every method is thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, socket.socket] = {}

    def join(self, nick: str, conn: socket.socket) -> bool:
        with self._lock:
            if nick.lower() in self._clients or len(self._clients) >= MAX_CLIENTS:
                return False
            self._clients[nick.lower()] = conn
            return True

    def leave(self, nick: str) -> None:
        with self._lock:
            self._clients.pop(nick.lower(), None)

    def broadcast(self, text: str) -> None:
        with self._lock:
            targets = list(self._clients.values())
        for conn in targets:
            conn.sendall(frame(text))


def handle_client(conn: socket.socket, room: Room) -> None:
    nick, buffer = None, b""
    with conn:
        while chunk := conn.recv(4096):
            messages, buffer = unframe(buffer + chunk)
            for line in messages:
                try:
                    command, args = parse_command(line)
                except ProtocolError as exc:
                    conn.sendall(frame(f"error: {exc}"))
                    continue
                if command == "nick" and args and room.join(args[0], conn):
                    nick = args[0]
                elif command == "say" and nick:
                    room.broadcast(f"{nick}: {args[0]}")
                elif command == "quit":
                    return
    if nick:
        room.leave(nick)


def serve() -> None:
    room = Room()
    with socket.create_server((HOST, PORT)) as server:
        while True:
            conn, _ = server.accept()
            threading.Thread(target=handle_client, args=(conn, room), daemon=True).start()


if __name__ == "__main__":
    serve()
