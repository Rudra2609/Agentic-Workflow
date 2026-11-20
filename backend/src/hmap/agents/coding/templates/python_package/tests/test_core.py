import unittest

from app import __version__
from app.core import normalise


class CoreTest(unittest.TestCase):
    def test_normalise(self):
        self.assertEqual(normalise("  Hello   World "), "hello world")

    def test_version(self):
        self.assertTrue(__version__)


if __name__ == "__main__":
    unittest.main()
