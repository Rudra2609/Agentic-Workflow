"""Command-line chat client."""

import argparse
import socket


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect to the chat server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()
    with socket.create_connection((args.host, args.port)) as conn:
        for line in iter(input, "/quit"):
            conn.sendall((line + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
