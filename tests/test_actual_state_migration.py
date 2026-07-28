import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

from core.migrations import m0038_actual_cutover_state as migration


class ActualStateMigrationTests(unittest.TestCase):
    def test_state_tables_are_additive_seeded_and_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'db.sqlite'}")
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE existing (id INTEGER PRIMARY KEY, value TEXT)"))
                conn.execute(text("INSERT INTO existing(value) VALUES ('untouched')"))
                migration.up(conn)
                first = conn.execute(
                    text(
                        "SELECT id,mode,base_currency_code,legacy_read_only FROM finance_ledger_state"
                    )
                ).one()
                migration.up(conn)
                second = conn.execute(
                    text(
                        "SELECT id,mode,base_currency_code,legacy_read_only FROM finance_ledger_state"
                    )
                ).one()
                existing = conn.execute(text("SELECT value FROM existing")).scalar_one()
                run_tables = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'actual_%'"
                        )
                    )
                }
            engine.dispose()
        self.assertEqual(first, second)
        self.assertEqual(tuple(first), ("primary", "alles", "CAD", 0))
        self.assertEqual(existing, "untouched")
        self.assertEqual(run_tables, {"actual_migration_runs", "actual_entity_links"})


if __name__ == "__main__":
    unittest.main()
