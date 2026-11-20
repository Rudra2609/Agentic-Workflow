import unittest

from room import Room


class Conn:
    def __init__(self, closed=False):
        self.closed, self.sent = closed, []

    def send(self, text):
        self.sent.append(text)


class T(unittest.TestCase):
    def test_closed_client_dropped(self):
        r = Room()
        a, gone, b = Conn(), Conn(closed=True), Conn()
        for nick, conn in (("a", a), ("gone", gone), ("b", b)):
            r.join(nick, conn)
        self.assertEqual(r.broadcast("hi"), 2)
        self.assertEqual((a.sent, b.sent), (["hi"], ["hi"]))
        self.assertTrue(r.join("gone", Conn()))
