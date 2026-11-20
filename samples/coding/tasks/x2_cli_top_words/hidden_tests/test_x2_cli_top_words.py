import contextlib
import io
import os
import tempfile
import unittest

from cli import main


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(args))
    return code, out.getvalue().strip().splitlines()


class TopTest(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir=".") as f:
            f.write("The cat and the dog. The END, and the cat!\n")
        self.path = f.name

    def tearDown(self):
        os.unlink(self.path)

    def test_top_two(self):
        self.assertEqual(run("top", self.path, "-n", "2"), (0, ["the 4", "and 2"]))

    def test_default_three_with_tie_order(self):
        self.assertEqual(run("top", self.path), (0, ["the 4", "and 2", "cat 2"]))

    def test_missing_file(self):
        self.assertEqual(run("top", "no-such-file.txt")[0], 1)


if __name__ == "__main__":
    unittest.main()
