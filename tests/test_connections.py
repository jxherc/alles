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

    def test_db_token_beats_env(self):
        # db row wins even when env var is set
        with (
            mock.patch.object(C, "get_connection", lambda s: SimpleNamespace(token="db-wins")),
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "env-loses"}),
        ):
            self.assertEqual(C.get_token("github"), "db-wins")

    def test_empty_db_token_falls_back_to_env(self):
        # a connection row exists but token is empty string → fall through to env
        with (
            mock.patch.object(C, "get_connection", lambda s: SimpleNamespace(token="")),
            mock.patch.dict(os.environ, {"SLACK_TOKEN": "slk-env"}),
        ):
            self.assertEqual(C.get_token("slack"), "slk-env")

    def test_token_env_wins_over_api_key(self):
        # _TOKEN takes precedence over _API_KEY when both exist
        env = {"OPENAI_TOKEN": "tok-first", "OPENAI_API_KEY": "key-second"}
        with (
            mock.patch.object(C, "get_connection", lambda s: None),
            mock.patch.dict(os.environ, env),
        ):
            self.assertEqual(C.get_token("openai"), "tok-first")

    def test_service_name_case_insensitive(self):
        # get_token upcases the service, so "GitHub" → "GITHUB_TOKEN"
        with (
            mock.patch.object(C, "get_connection", lambda s: None),
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "case-tok"}),
        ):
            self.assertEqual(C.get_token("GitHub"), "case-tok")

    def test_list_connections_returns_list(self):
        # list_connections() goes to the real DB, but with an in-memory mock it returns []
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        import core.database as db

        eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(eng)
        orig = db.engine
        db.engine = eng
        db.SessionLocal.configure(bind=eng)
        try:
            result = C.list_connections()
            self.assertIsInstance(result, list)
            self.assertEqual(result, [])
        finally:
            db.SessionLocal.configure(bind=orig)
            db.engine = orig
            eng.dispose()


if __name__ == "__main__":
    unittest.main()
