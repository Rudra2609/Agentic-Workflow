import unittest

from framing import frame, unframe


class T(unittest.TestCase):
    def test_exact_frame(self):
        self.assertEqual(unframe(frame("hi")), (["hi"], b""))

    def test_partial_waits(self):
        self.assertEqual(unframe(frame("hi")[:-1]), ([], frame("hi")[:-1]))
