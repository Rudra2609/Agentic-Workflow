import unittest

from framing import frame, unframe


class T(unittest.TestCase):
    def test_frame_layout(self):
        self.assertEqual(frame("hi"), b"\x00\x00\x00\x02hi")

    def test_round_trip(self):
        self.assertEqual(unframe(frame("a") + frame("héllo")), (["a", "héllo"], b""))

    def test_partial(self):
        data = frame("one") + frame("two")
        self.assertEqual(unframe(data[:-1]), (["one"], data[7:-1]))
        self.assertEqual(unframe(b"\x00\x00"), ([], b"\x00\x00"))
