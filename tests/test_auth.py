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
        self.assertFalse(auth.verify_session(t))  # not stored yet
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
        t = auth.create_session_token()
        auth.store_token(t)
        code = auth.make_handoff(t)
        self.assertEqual(auth.redeem_handoff(code), t)
        self.assertIsNone(auth.redeem_handoff(code))  # consumed

    def test_expired_handoff(self):
        t = auth.create_session_token()
        auth.store_token(t)
        code = auth.make_handoff(t, ttl=0)
        with mock.patch("core.auth.time.time", return_value=time.time() + 5):
            self.assertIsNone(auth.redeem_handoff(code))

    def test_bad_code(self):
        self.assertIsNone(auth.redeem_handoff("does-not-exist"))


class LoginThrottleTests(unittest.TestCase):
    def setUp(self):
        auth._login_fails.clear()

    def test_blocks_after_max_fails(self):
        ip = "1.2.3.4"
        for _ in range(auth._LOGIN_MAX_FAILS):
            self.assertFalse(auth.login_blocked(ip))
            auth.record_login_fail(ip)
        self.assertTrue(auth.login_blocked(ip))

    def test_good_login_clears(self):
        ip = "5.6.7.8"
        for _ in range(auth._LOGIN_MAX_FAILS):
            auth.record_login_fail(ip)
        self.assertTrue(auth.login_blocked(ip))
        auth.clear_login_fails(ip)
        self.assertFalse(auth.login_blocked(ip))

    def test_window_expires(self):
        ip = "9.9.9.9"
        for _ in range(auth._LOGIN_MAX_FAILS):
            auth.record_login_fail(ip)
        self.assertTrue(auth.login_blocked(ip))
        with mock.patch("core.auth.time.time", return_value=time.time() + auth._LOGIN_WINDOW + 1):
            self.assertFalse(auth.login_blocked(ip))

    def test_per_ip(self):
        for _ in range(auth._LOGIN_MAX_FAILS):
            auth.record_login_fail("attacker")
        self.assertTrue(auth.login_blocked("attacker"))
        self.assertFalse(auth.login_blocked("someone-else"))


if __name__ == "__main__":
    unittest.main()
