"""Command-line chat client."""

import argparse
import socket
import threading

from protocol import frame, unframe


def receive(conn: socket.socket) -> None:
    buffer = b""
    while chunk := conn.recv(4096):
        messages, buffer = unframe(buffer + chunk)
        for message in messages:
            print(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect to the chat server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--nick", required=True)
    args = parser.parse_args()
    with socket.create_connection((args.host, args.port)) as conn:
        conn.sendall(frame(f"/nick {args.nick}"))
        threading.Thread(target=receive, args=(conn,), daemon=True).start()
        for line in iter(input, "/quit"):
            conn.sendall(frame(line))


if __name__ == "__main__":
    main()
