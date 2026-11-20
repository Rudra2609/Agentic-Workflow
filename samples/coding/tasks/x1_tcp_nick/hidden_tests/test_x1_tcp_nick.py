import time
import unittest

from client import ChatClient
from server import ChatServer


class NickTest(unittest.TestCase):
    def setUp(self):
        self.server = ChatServer("127.0.0.1", 0)
        self.port = self.server.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.server.stop()

    def connect(self):
        c = ChatClient("127.0.0.1", self.port, timeout=3)
        self.clients.append(c)
        deadline = time.time() + 3
        while self.server.client_count() < len(self.clients) and time.time() < deadline:
            time.sleep(0.01)
        return c

    def test_nick_prefixes_messages_and_is_not_broadcast(self):
        a, b = self.connect(), self.connect()
        a.send("/nick alice")
        time.sleep(0.2)
        a.send("hello")
        self.assertEqual(b.receive(), "alice: hello")

    def test_default_names_and_concurrent_clients(self):
        a, b, c = self.connect(), self.connect(), self.connect()
        b.send("hi")
        self.assertTrue(a.receive().endswith(": hi"))
        self.assertTrue(c.receive().endswith(": hi"))


if __name__ == "__main__":
    unittest.main()
