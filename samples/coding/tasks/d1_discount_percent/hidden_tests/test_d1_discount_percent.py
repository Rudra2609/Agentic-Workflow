import unittest

from pricing.discounts import apply_discount


class DiscountTest(unittest.TestCase):
    def test_percent_codes(self):
        self.assertEqual(apply_discount(200, "SAVE10"), 180)
        self.assertEqual(apply_discount(80, "save25"), 60)

    def test_amount_and_unknown(self):
        self.assertEqual(apply_discount(50, "FLAT5"), 45)
        self.assertEqual(apply_discount(50, "NOPE"), 50)


if __name__ == "__main__":
    unittest.main()
