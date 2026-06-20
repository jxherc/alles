import unittest

from services.routing import is_local_endpoint, pick_endpoint


class _EP:
    def __init__(self, base_url, enabled=True):
        self.base_url = base_url
        self.enabled = enabled


class RoutingTest(unittest.TestCase):
    def test_is_local(self):
        self.assertTrue(is_local_endpoint(_EP("http://localhost:11434")))
        self.assertTrue(is_local_endpoint(_EP("http://127.0.0.1:1234/v1")))
        self.assertFalse(is_local_endpoint(_EP("https://api.deepseek.com")))

    def test_default_picks_first(self):
        eps = [_EP("https://api.deepseek.com"), _EP("http://localhost:11434")]
        self.assertEqual(pick_endpoint(eps).base_url, "https://api.deepseek.com")

    def test_prefer_local_picks_local_when_present(self):
        eps = [_EP("https://api.deepseek.com"), _EP("http://localhost:11434")]
        self.assertEqual(pick_endpoint(eps, prefer_local=True).base_url, "http://localhost:11434")

    def test_prefer_local_falls_back_when_no_local(self):
        eps = [_EP("https://api.deepseek.com"), _EP("https://api.openai.com")]
        self.assertEqual(pick_endpoint(eps, prefer_local=True).base_url, "https://api.deepseek.com")

    def test_skips_disabled_and_handles_empty(self):
        self.assertIsNone(pick_endpoint([]))
        eps = [_EP("https://api.deepseek.com", enabled=False), _EP("http://localhost:11434")]
        self.assertEqual(pick_endpoint(eps).base_url, "http://localhost:11434")

    def test_all_disabled_returns_none(self):
        eps = [
            _EP("https://api.deepseek.com", enabled=False),
            _EP("http://localhost:11434", enabled=False),
        ]
        self.assertIsNone(pick_endpoint(eps))

    def test_ollama_hint_is_local(self):
        # some setups use 'ollama' in the URL without localhost
        self.assertTrue(is_local_endpoint(_EP("http://ollama:11434")))

    def test_zero_dot_zero_is_local(self):
        self.assertTrue(is_local_endpoint(_EP("http://0.0.0.0:8080/v1")))

    def test_prefer_local_single_remote_ep(self):
        # only one ep, remote — prefer_local should still return it (fallback)
        ep = _EP("https://api.openai.com")
        self.assertEqual(pick_endpoint([ep], prefer_local=True).base_url, "https://api.openai.com")

    def test_prefer_local_false_returns_first_even_if_local(self):
        # without prefer_local, first wins regardless of locality
        eps = [_EP("http://localhost:11434"), _EP("https://api.openai.com")]
        self.assertEqual(pick_endpoint(eps, prefer_local=False).base_url, "http://localhost:11434")


if __name__ == "__main__":
    unittest.main()
