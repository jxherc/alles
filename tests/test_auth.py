import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError
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
    def setUp(self):
        auth._tokens.clear()
        auth._recent_auth.clear()

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

    def test_new_session_is_recent_then_expires_for_sensitive_actions(self):
        token = auth.create_session_token()
        now = time.time()
        with mock.patch("core.auth.time.time", return_value=now):
            auth.store_token(token)
            self.assertTrue(auth.verify_recent_session(token))
        with mock.patch("core.auth.time.time", return_value=now + auth.RECENT_AUTH_SECONDS + 1):
            self.assertTrue(auth.verify_session(token))
            self.assertFalse(auth.verify_recent_session(token))

    def test_revoke_clears_recent_auth(self):
        token = auth.create_session_token()
        auth.store_token(token)
        auth.revoke_token(token)
        self.assertNotIn(token, auth._recent_auth)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        auth._handoff.clear()
        auth._context_handoff.clear()

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

    def test_context_handoff_is_session_bound_and_single_use(self):
        token = auth.create_session_token()
        other = auth.create_session_token()
        auth.store_token(token)
        auth.store_token(other)
        payload = {"ask": "summarize", "document_scope": {"path": "private.md"}}
        code = auth.make_context_handoff(token, payload)

        self.assertIsNone(auth.redeem_context_handoff(code, other))
        self.assertEqual(auth.redeem_context_handoff(code, token), payload)
        self.assertIsNone(auth.redeem_context_handoff(code, token))

    def test_context_handoff_is_single_use_under_concurrent_redemption(self):
        token = auth.create_session_token()
        auth.store_token(token)
        payload = {"ask": "one owner only"}
        code = auth.make_context_handoff(token, payload)
        barrier = Barrier(2)
        original_compare = auth.secrets.compare_digest

        def synchronize_compare(left, right):
            try:
                barrier.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
            return original_compare(left, right)

        with mock.patch.object(auth.secrets, "compare_digest", side_effect=synchronize_compare):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(lambda _: auth.redeem_context_handoff(code, token), range(2))
                )

        self.assertEqual(results.count(payload), 1)
        self.assertEqual(results.count(None), 1)

    def test_context_handoff_expires(self):
        token = auth.create_session_token()
        auth.store_token(token)
        code = auth.make_context_handoff(token, {"ask": "private"}, ttl=0)
        with mock.patch("core.auth.time.time", return_value=time.time() + 5):
            self.assertIsNone(auth.redeem_context_handoff(code, token))

    def test_context_handoff_prunes_expired_entries_on_create_and_redeem(self):
        token = auth.create_session_token()
        auth.store_token(token)
        auth._context_handoff["expired-create"] = (0, token, {"old": True})
        code = auth.make_context_handoff(token, {"fresh": True})
        self.assertNotIn("expired-create", auth._context_handoff)

        auth._context_handoff["expired-redeem"] = (0, token, {"old": True})
        self.assertEqual(auth.redeem_context_handoff(code, token), {"fresh": True})
        self.assertNotIn("expired-redeem", auth._context_handoff)

    def test_context_handoff_store_is_bounded(self):
        token = auth.create_session_token()
        auth.store_token(token)
        with mock.patch.object(auth, "_CONTEXT_HANDOFF_MAX", 2):
            codes = [auth.make_context_handoff(token, {"index": index}) for index in range(3)]
        self.assertLessEqual(len(auth._context_handoff), 2)
        self.assertNotIn(codes[0], auth._context_handoff)
        self.assertIn(codes[-1], auth._context_handoff)


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
