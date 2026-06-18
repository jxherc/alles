import os
import unittest
from types import SimpleNamespace
from unittest import mock

from services import connections as C


class TokenTests(unittest.TestCase):
    def test_db_token_wins(self):
        with mock.patch.object(C, "get_connection", lambda s: SimpleNamespace(token="db-tok")):
            self.assertEqual(C.get_token("github"), "db-tok")

    def test_env_token_fallback(self):
        with (
            mock.patch.object(C, "get_connection", lambda s: None),
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "env-tok"}),
        ):
            self.assertEqual(C.get_token("github"), "env-tok")

    def test_api_key_fallback(self):
        env = {"OPENAI_API_KEY": "key-123"}
        with (
            mock.patch.object(C, "get_connection", lambda s: None),
            mock.patch.dict(os.environ, env),
        ):
            os.environ.pop("OPENAI_TOKEN", None)
            self.assertEqual(C.get_token("openai"), "key-123")

    def test_none_when_nothing(self):
        with (
            mock.patch.object(C, "get_connection", lambda s: None),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(C.get_token("nonexistent"), "")


if __name__ == "__main__":
    unittest.main()
