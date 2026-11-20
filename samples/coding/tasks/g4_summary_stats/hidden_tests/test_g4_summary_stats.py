import unittest

from numstats import summarize


class T(unittest.TestCase):
    def test_odd(self):
        self.assertEqual(summarize([3, 1, 2]), {"min": 1, "max": 3, "mean": 2, "median": 2})

    def test_even(self):
        self.assertEqual(summarize([4, 1, 3, 2])["median"], 2.5)

    def test_empty(self):
        with self.assertRaises(ValueError):
            summarize([])
