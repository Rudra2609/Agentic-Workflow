import unittest

from auth.tokens import token_expired


class TokenTest(unittest.TestCase):
    def test_ttl(self):
        self.assertFalse(token_expired(0, 3600))
        self.assertTrue(token_expired(0, 3601))
