import time
import unittest
from unittest import mock

from core import auth


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self):
        h = auth.hash_password("s3cret")
        self.assertNotEqual(h, "s3cret")
        self.assertTrue(auth.verify_password("s3cret", h))
        self.assertFalse(auth.verify_password("wrong", h))

    def test_verify_garbage_hash(self):
        self.assertFalse(auth.verify_password("x", "not-a-bcrypt-hash"))


class SessionTokenTests(unittest.TestCase):
    def test_store_verify_revoke(self):
        t = auth.create_session_token()
        self.assertFalse(auth.verify_session(t))      # not stored yet
        auth.store_token(t, ttl_days=1)
        self.assertTrue(auth.verify_session(t))
        auth.revoke_token(t)
        self.assertFalse(auth.verify_session(t))

    def test_expired(self):
        t = auth.create_session_token()
        auth.store_token(t, ttl_days=1)
        with mock.patch("core.auth.time.time", return_value=time.time() + 2 * 86400):
            self.assertFalse(auth.verify_session(t))


class HandoffTests(unittest.TestCase):
    def test_single_use(self):
        t = auth.create_session_token(); auth.store_token(t)
        code = auth.make_handoff(t)
        self.assertEqual(auth.redeem_handoff(code), t)
        self.assertIsNone(auth.redeem_handoff(code))   # consumed

    def test_expired_handoff(self):
        t = auth.create_session_token(); auth.store_token(t)
        code = auth.make_handoff(t, ttl=0)
        with mock.patch("core.auth.time.time", return_value=time.time() + 5):
            self.assertIsNone(auth.redeem_handoff(code))

    def test_bad_code(self):
        self.assertIsNone(auth.redeem_handoff("does-not-exist"))


if __name__ == "__main__":
    unittest.main()
