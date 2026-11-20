import unittest

from protocol import parse_command


class T(unittest.TestCase):
    def test_commands(self):
        self.assertEqual(parse_command("/nick alice"), ("nick", ["alice"]))
        self.assertEqual(parse_command("/msg bob hi there"), ("msg", ["bob", "hi there"]))
        self.assertEqual(parse_command("/quit"), ("quit", []))
        self.assertEqual(parse_command("/who"), ("who", []))

    def test_text_and_whitespace(self):
        self.assertEqual(parse_command("  hello world \n"), ("say", ["hello world"]))

    def test_unknown(self):
        with self.assertRaises(ValueError):
            parse_command("/dance")
