import threading
import unittest

from registry import NickRegistry


class T(unittest.TestCase):
    def test_unique_case_insensitive(self):
        r = NickRegistry()
        self.assertTrue(r.register("Alice", 1))
        self.assertFalse(r.register("alice", 2))
        r.unregister("ALICE")
        self.assertTrue(r.register("alice", 3))
        self.assertEqual(r.names(), ["alice"])

    def test_invalid(self):
        for bad in ("", "a" * 17, "bad name", "x!"):
            with self.assertRaises(ValueError):
                NickRegistry().register(bad, 1)

    def test_threads(self):
        r, results = NickRegistry(), []
        threads = [threading.Thread(target=lambda i=i: results.append(r.register("same", i))) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 1)
