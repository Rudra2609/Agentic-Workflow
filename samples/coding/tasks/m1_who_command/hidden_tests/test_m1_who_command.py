import unittest

from protocol import parse_command


class T(unittest.TestCase):
    def test_who(self):
        self.assertEqual(parse_command("/who"), ("who", []))

    def test_existing(self):
        self.assertEqual(parse_command("/msg bob hi"), ("msg", ["bob", "hi"]))
        self.assertEqual(parse_command("/quit"), ("quit", []))
        with self.assertRaises(ValueError):
            parse_command("/dance")
