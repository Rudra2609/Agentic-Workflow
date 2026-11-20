"""The chat room: connected clients by nickname."""

import threading


class Room:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, object] = {}

    def join(self, nick: str, conn: object) -> bool:
        """Add a client; False if the nickname is taken (case-insensitive)."""
        with self._lock:
            if nick.lower() in self._clients:
                return False
            self._clients[nick.lower()] = conn
            return True

    def leave(self, nick: str) -> None:
        with self._lock:
            self._clients.pop(nick.lower(), None)

    def broadcast(self, text: str) -> int:
        """Send text to every open connection, drop closed ones; return how many got it."""
        sent = 0
        with self._lock:
            for nick, conn in self._clients.items():
                if conn.closed:
                    del self._clients[nick]
                    continue
                conn.send(text)
                sent += 1
        return sent
