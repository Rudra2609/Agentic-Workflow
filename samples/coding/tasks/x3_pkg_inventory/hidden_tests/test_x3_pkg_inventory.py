import unittest

from app.inventory import Inventory


class InventoryTest(unittest.TestCase):
    def test_add_and_stock(self):
        inv = Inventory()
        inv.add("pen", 3)
        inv.add("pen", 2)
        self.assertEqual(inv.stock("pen"), 5)
        self.assertEqual(inv.stock("ink"), 0)

    def test_remove_too_much_changes_nothing(self):
        inv = Inventory()
        inv.add("pen", 2)
        with self.assertRaises(ValueError):
            inv.remove("pen", 3)
        self.assertEqual(inv.stock("pen"), 2)
        inv.remove("pen", 2)
        self.assertEqual(inv.stock("pen"), 0)

    def test_bad_quantities(self):
        inv = Inventory()
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                inv.add("pen", bad)


if __name__ == "__main__":
    unittest.main()
