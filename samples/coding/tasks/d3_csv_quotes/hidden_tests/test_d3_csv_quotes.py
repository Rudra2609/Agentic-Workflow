import unittest

from io_utils.csv_reader import split_line
from report import shape


class QuotesTest(unittest.TestCase):
    def test_quoted_comma(self):
        self.assertEqual(split_line('1,"Smith, John",3'), ["1", "Smith, John", "3"])

    def test_doubled_quote(self):
        self.assertEqual(split_line('"say ""hi""",x'), ['say "hi"', "x"])

    def test_plain(self):
        self.assertEqual(split_line("a, b,c"), ["a", "b", "c"])
        self.assertEqual(shape('a,"b,c"\nd,e\n'), (2, 2))


if __name__ == "__main__":
    unittest.main()
