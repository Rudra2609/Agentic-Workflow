import unittest

from lru import LRUCache


class T(unittest.TestCase):
    def test_eviction_order(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        self.assertEqual(c.get("a"), 1)
        c.put("c", 3)
        self.assertIsNone(c.get("b"))
        self.assertEqual((c.get("a"), c.get("c"), len(c)), (1, 3, 2))

    def test_update_counts_as_use(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        c.put("a", 10)
        c.put("c", 3)
        self.assertEqual((c.get("a"), c.get("b", "gone")), (10, "gone"))
