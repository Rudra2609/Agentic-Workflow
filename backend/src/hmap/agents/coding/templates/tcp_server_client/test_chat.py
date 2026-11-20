import time
import unittest

from client import ChatClient
from protocol import LineReader, encode
from server import ChatServer


class ProtocolTest(unittest.TestCase):
    def test_round_trip_and_partial_lines(self):
        reader = LineReader()
        data = encode("hello") + encode("two words")
        self.assertEqual(reader.feed(data[:3]), [])
        self.assertEqual(reader.feed(data[3:]), ["hello", "two words"])

    def test_newlines_inside_a_message_do_not_split_it(self):
        self.assertEqual(encode("a\nb"), b"a b\n")


class ChatServerTest(unittest.TestCase):
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

    def test_message_reaches_every_other_client(self):
        a, b, c = self.connect(), self.connect(), self.connect()
        a.send("hi all")
        self.assertTrue(b.receive().endswith("hi all"))
        self.assertTrue(c.receive().endswith("hi all"))

    def test_clients_are_served_at_the_same_time(self):
        a, b = self.connect(), self.connect()
        b.send("from b while a is connected")
        self.assertIn("from b", a.receive())

    def test_disconnect_does_not_break_the_others(self):
        a, b, c = self.connect(), self.connect(), self.connect()
        b.close()
        self.clients.remove(b)
        deadline = time.time() + 3
        while self.server.client_count() > 2 and time.time() < deadline:
            time.sleep(0.01)
        a.send("still here")
        self.assertTrue(c.receive().endswith("still here"))


if __name__ == "__main__":
    unittest.main()
