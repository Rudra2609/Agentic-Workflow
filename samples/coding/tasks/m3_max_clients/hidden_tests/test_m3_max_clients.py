import unittest

from room import Room


class T(unittest.TestCase):
    def test_limit(self):
        r = Room(max_clients=2)
        self.assertTrue(r.join("a", object()))
        self.assertTrue(r.join("b", object()))
        self.assertFalse(r.join("c", object()))
        r.leave("a")
        self.assertTrue(r.join("c", object()))

    def test_default(self):
        r = Room()
        self.assertTrue(all(r.join(f"n{i}", object()) for i in range(32)))
        self.assertFalse(r.join("extra", object()))
