"""Acceptance test for the Sprint 8 demo (the assignment's own multi-client check). Black box: starts
``python server.py --port <port>`` as a process and talks to it over TCP with three clients, like a teacher's test.

Protocol (from the assignment): clients are named client1, client2, ... in the order they connect; every line a
client sends goes to every OTHER client as ``<name>: <text>``; ``/who`` is answered only to the sender with
``online: `` + the names, sorted and comma-separated, and is not broadcast.
"""

import select
import socket
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server():
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-u", "server.py", "--port", str(port)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    # wait for the start-up line (a probe connection would itself become client1)
    ready, _, _ = select.select([proc.stdout], [], [], 5)
    assert ready and proc.stdout is not None and proc.stdout.readline(), "the server did not start"
    yield port
    proc.kill()
    proc.wait(timeout=5)


class Client:
    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.buf = b""
        time.sleep(0.15)          # connection order = names client1, client2, ...

    def send(self, line: str) -> None:
        self.sock.sendall(line.encode() + b"\n")

    def line(self) -> str:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        raw, self.buf = self.buf.split(b"\n", 1)
        return raw.decode().strip()

    def silent(self, wait: float = 0.3) -> bool:
        self.sock.settimeout(wait)
        try:
            return not self.sock.recv(4096)
        except TimeoutError:
            return True
        finally:
            self.sock.settimeout(3)

    def close(self) -> None:
        self.sock.close()


def test_a_message_reaches_every_other_client(server: int) -> None:
    one, two, three = Client(server), Client(server), Client(server)
    one.send("hello all")
    assert two.line() == "client1: hello all"
    assert three.line() == "client1: hello all"
    assert one.silent()
    for c in (one, two, three):
        c.close()


def test_who_lists_the_online_clients_to_the_sender_only(server: int) -> None:
    one, two, three = Client(server), Client(server), Client(server)
    two.send("/who")
    assert two.line() == "online: client1, client2, client3"
    assert one.silent() and three.silent()
    for c in (one, two, three):
        c.close()
