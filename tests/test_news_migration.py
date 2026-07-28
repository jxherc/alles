import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from core.migrations import m0041_scheduled_news


class ScheduledNewsMigrationTests(unittest.TestCase):
    def test_migration_is_idempotent_and_preserves_existing_data(self):
        with tempfile.TemporaryDirectory(prefix="alles-news-schema-") as temp:
            engine = create_engine(f"sqlite:///{Path(temp) / 'legacy.db'}")
            with engine.begin() as conn:
                conn.execute(
                    text("CREATE TABLE existing_data (id INTEGER PRIMARY KEY, value TEXT)")
                )
                conn.execute(text("INSERT INTO existing_data (value) VALUES ('keep me')"))

                m0041_scheduled_news.up(conn)
                m0041_scheduled_news.up(conn)

                inspector = inspect(conn)
                tables = set(inspector.get_table_names())
                entry_indexes = {item["name"] for item in inspector.get_indexes("news_entries")}
                brief_indexes = {item["name"] for item in inspector.get_indexes("news_briefs")}
                existing = conn.execute(text("SELECT value FROM existing_data")).scalar_one()

            engine.dispose()

        self.assertTrue(
            {
                "news_configuration",
                "news_sources",
                "news_entries",
                "news_briefs",
            }.issubset(tables)
        )
        self.assertEqual(existing, "keep me")
        self.assertIn("ix_news_entries_cluster", entry_indexes)
        self.assertIn("ix_news_entries_hash", entry_indexes)
        self.assertIn("ix_news_briefs_jarvis_retry", brief_indexes)


if __name__ == "__main__":
    unittest.main()
