import unittest

from io_utils.csv_writer import write_line


class WriterTest(unittest.TestCase):
    def test_quotes(self):
        self.assertEqual(write_line(["a", "b,c"]), 'a,"b,c"')
