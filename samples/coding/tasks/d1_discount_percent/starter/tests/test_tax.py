import unittest

from pricing.tax import add_tax


class TaxTest(unittest.TestCase):
    def test_default_rate(self):
        self.assertEqual(add_tax(100), 108.0)
