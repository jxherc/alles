import unittest

from sqlalchemy import create_engine, text

from core.migrations import m0019_api_token_scopes as migration


class ApiTokenScopeMigrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE api_tokens ("
                    "id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL, "
                    "prefix TEXT NOT NULL, created_at DATETIME, last_used_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO api_tokens (id, name, token_hash, prefix) "
                    "VALUES ('old', 'old token', 'hash', 'alles_old')"
                )
            )

    def tearDown(self):
        self.engine.dispose()

    def test_existing_tokens_migrate_to_read_only_and_migration_is_idempotent(self):
        with self.engine.begin() as connection:
            migration.up(connection)
            migration.up(connection)
            row = connection.execute(text("SELECT scopes FROM api_tokens WHERE id = 'old'")).one()
        self.assertEqual(row[0], '["read"]')


if __name__ == "__main__":
    unittest.main()
