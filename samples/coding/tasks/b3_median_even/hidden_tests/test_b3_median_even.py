import unittest

import stats


class T(unittest.TestCase):
    def test_median(self):
        self.assertEqual(stats.median([1, 2, 3, 4]), 2.5)
        self.assertEqual(stats.median([3, 1, 2]), 2)

    def test_summary_uses_it(self):
        rows = [{"s": str(v)} for v in (1, 2, 3, 4)]
        self.assertEqual(stats.summarize(rows)["s"]["median"], 2.5)
