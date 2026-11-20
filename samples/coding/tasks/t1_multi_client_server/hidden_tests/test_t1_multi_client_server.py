import socket
import threading
import unittest

from server import EchoServer


def ask(conn, text):
    conn.sendall((text + "\n").encode())
    return conn.makefile("r").readline().strip()


class T(unittest.TestCase):
    def setUp(self):
        self.server = EchoServer()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def connect(self):
        conn = socket.create_connection(("127.0.0.1", self.server.port), timeout=3)
        self.addCleanup(conn.close)
        return conn

    def test_single_client(self):
        self.assertEqual(ask(self.connect(), "hi"), "echo: hi")

    def test_second_client_while_first_connected(self):
        first = self.connect()
        self.assertEqual(ask(first, "one"), "echo: one")
        second = self.connect()
        self.assertEqual(ask(second, "two"), "echo: two")  # times out if clients are served one at a time
