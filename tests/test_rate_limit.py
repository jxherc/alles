import unittest

from core import rate_limit


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        rate_limit._events.clear()

    def test_limit_returns_retry_time_then_recovers_after_window(self):
        self.assertEqual(
            rate_limit.check_rate_limit("backup", "client", limit=2, window_seconds=10, now=0),
            0,
        )
        self.assertEqual(
            rate_limit.check_rate_limit("backup", "client", limit=2, window_seconds=10, now=1),
            0,
        )
        self.assertEqual(
            rate_limit.check_rate_limit("backup", "client", limit=2, window_seconds=10, now=2),
            8,
        )
        self.assertEqual(
            rate_limit.check_rate_limit("backup", "client", limit=2, window_seconds=10, now=11),
            0,
        )

    def test_actions_and_clients_have_separate_buckets(self):
        rate_limit.check_rate_limit("backup", "one", limit=1, window_seconds=10, now=0)
        self.assertGreater(
            rate_limit.check_rate_limit("backup", "one", limit=1, window_seconds=10, now=1),
            0,
        )
        self.assertEqual(
            rate_limit.check_rate_limit("tokens", "one", limit=1, window_seconds=10, now=1),
            0,
        )
        self.assertEqual(
            rate_limit.check_rate_limit("backup", "two", limit=1, window_seconds=10, now=1),
            0,
        )


if __name__ == "__main__":
    unittest.main()
