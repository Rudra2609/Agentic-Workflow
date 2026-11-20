import contextlib
import io
import os
import tempfile
import unittest

from cli import count, main


class CliTest(unittest.TestCase):
    def test_count(self):
        self.assertEqual(count("a b\nc\n"), {"lines": 2, "words": 3, "chars": 6})

    def test_main_reads_a_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir=".") as f:
            f.write("one two\n")
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["count", f.name]), 0)
        finally:
            os.unlink(f.name)
        self.assertIn("words=2", out.getvalue())

    def test_missing_file_is_an_error_exit(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["count", "no-such-file.txt"]), 1)


if __name__ == "__main__":
    unittest.main()
