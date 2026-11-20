import unittest

from auth.sessions import is_expired
from web.login import still_logged_in


class SessionTest(unittest.TestCase):
    def test_minutes_not_seconds(self):
        self.assertFalse(is_expired(0, 60))
        self.assertFalse(is_expired(0, 30 * 60))
        self.assertTrue(is_expired(0, 31 * 60))
        self.assertTrue(still_logged_in(1000, 1000 + 25 * 60))


if __name__ == "__main__":
    unittest.main()
